"""租约配置和升级门禁，禁止带未确认清理直接迁移。"""

import json
import sqlite3
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from runbridge_hub.app import create_app
from runbridge_hub.security import token_hash
from runbridge_hub.maintenance import confirm_cleanup
from runbridge_hub.settings import HubSettings
from runbridge_hub.startup import ServeSettings
from test_leases import claim, ready
from test_r1 import ENROLLMENT, HUB, IDENTITY, auth, settings


@pytest.mark.parametrize("field", ["grant_max_lease_seconds", "grant_idle_timeout_seconds"])
@pytest.mark.parametrize("value", [0, -1, 1.1, True, "600"])
def test_lease_settings_require_positive_integer(field, value):
    with pytest.raises(ValidationError):
        HubSettings(enrollment_token=ENROLLMENT, **{field: value})


def test_hub_credential_file_and_config_relative_paths(tmp_path, monkeypatch):
    (tmp_path / "enrollment.token").write_text(ENROLLMENT)
    (tmp_path / "pool.token").write_text(HUB)
    path = tmp_path / "hub.yaml"
    path.write_text("enrollment_token_file: enrollment.token\nhub_token_file: pool.token\npublic_url: https://hub.test/prefix/\ngrant_max_lease_seconds: 90000\ngrant_idle_timeout_seconds: 77\n")
    monkeypatch.setenv("RUNBRIDGE_HUB_TOKEN", "environment-" + "x" * 40)
    startup = ServeSettings.load(path=path)
    assert startup.hub_token_file == tmp_path / "pool.token"
    config = startup.hub_settings()
    assert config.hub_token.get_secret_value() == HUB
    assert config.public_url == "https://hub.test/prefix"
    assert config.grant_max_lease_seconds == 90000 and config.grant_idle_timeout_seconds == 77
    assert HUB not in repr(config)


def test_missing_hub_config_never_falls_back_to_enrollment(tmp_path):
    config = settings(tmp_path=tmp_path).model_copy(update={"hub_token": None})
    with TestClient(app=create_app(settings=config)) as client:
        response = client.get(url="/v1/pool/nodes", headers=auth(token=ENROLLMENT))
        assert response.status_code == 503 and response.json()["code"] == "HUB_ACCESS_NOT_CONFIGURED"


def test_export_requires_explicit_public_url(tmp_path):
    config = settings(tmp_path=tmp_path).model_copy(update={"public_url": None})
    with TestClient(app=create_app(settings=config)) as client, ready(client=client):
        response = claim(client=client)
        assert response.status_code == 503 and response.json()["code"] == "PUBLIC_URL_REQUIRED"


@pytest.mark.parametrize("token", [ENROLLMENT, "web-token-" + "w" * 40])
def test_hub_token_cannot_reuse_other_roles(token):
    with pytest.raises(ValidationError):
        HubSettings(enrollment_token=ENROLLMENT, hub_token=token, web_token="web-token-" + "w" * 40)


def legacy_database(*, path, unclean=False):
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE nodes (node_id TEXT PRIMARY KEY,name TEXT NOT NULL,token_hash TEXT NOT NULL,generation INTEGER NOT NULL DEFAULT 0,capabilities TEXT,capabilities_observed_at TEXT,last_seen_at TEXT);
            CREATE TABLE grants (grant_id TEXT PRIMARY KEY,node_id TEXT NOT NULL REFERENCES nodes(node_id),token_hash TEXT NOT NULL UNIQUE,resource_ids TEXT,created_at TEXT NOT NULL,expires_at TEXT,revoked_at TEXT);
            CREATE TABLE sessions (session_id TEXT PRIMARY KEY,node_id TEXT NOT NULL REFERENCES nodes(node_id),grant_id TEXT NOT NULL REFERENCES grants(grant_id),record TEXT NOT NULL);
            PRAGMA user_version=4;
        """)
        db.execute("INSERT INTO nodes(node_id,name,token_hash) VALUES ('node_a','legacy',?)", (token_hash(token=IDENTITY),))
        for grant_id in ["old_a", "old_b"]:
            db.execute("INSERT INTO grants(grant_id,node_id,token_hash,created_at) VALUES (?,'node_a',?,'2026-01-01T00:00:00+00:00')", (grant_id, token_hash(token=grant_id)))
        if unclean:
            db.execute("INSERT INTO sessions VALUES ('old_session','node_a','old_a',?)", (json.dumps({"state": "INTERRUPTED", "cleanup": "UNKNOWN"}),))


def test_migration_revokes_all_old_grants_and_keeps_identity_and_backup(tmp_path):
    config = settings(tmp_path=tmp_path)
    legacy_database(path=config.database_path)
    with TestClient(app=create_app(settings=config)) as client:
        assert client.get(url="/v1/nodes/node_a", headers=auth(token="old_a")).status_code == 401
        with client.websocket_connect(url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            assert control.receive_json()["connection_generation"] == 1
    with sqlite3.connect(config.database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 5
        assert db.execute("SELECT state FROM grants").fetchall() == [("RELEASED",), ("RELEASED",)]
        assert db.execute("SELECT token_hash FROM nodes").fetchone()[0] == token_hash(token=IDENTITY)
    backups = list(tmp_path.glob("*.pre-lease-*.bak"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert db.execute("SELECT revoked_at FROM grants").fetchall() == [(None,), (None,)]


def test_migration_refuses_unknown_cleanup_without_rewriting_history(tmp_path):
    config = settings(tmp_path=tmp_path)
    legacy_database(path=config.database_path, unclean=True)
    with pytest.raises(RuntimeError, match="升级租约前必须排空"):
        with TestClient(app=create_app(settings=config)):
            pass
    with sqlite3.connect(config.database_path) as db:
        assert db.execute("PRAGMA user_version").fetchone()[0] == 4
        assert json.loads(db.execute("SELECT record FROM sessions").fetchone()[0])["cleanup"] == "UNKNOWN"


def test_offline_cleanup_resolution_preserves_unknown_and_allows_migration(tmp_path):
    config = settings(tmp_path=tmp_path)
    legacy_database(path=config.database_path, unclean=True)
    evidence = tmp_path / "evidence.json"
    evidence.write_text(json.dumps({"node_id": "node_a", "grant_id": "old_a", "checked_at": datetime.now(UTC).isoformat(),
                                    "details": "模拟维护证据：设备已停止，原范围进程和临时目录均已核查；非真机验收"}))
    confirm_cleanup(database_path=config.database_path, grant_id="old_a", evidence_file=evidence)
    confirm_cleanup(database_path=config.database_path, grant_id="old_a", evidence_file=evidence)
    with TestClient(app=create_app(settings=config)) as client:
        async def resolved():
            store = client.app.state.service.store
            return await store.node_unclean(node_id="node_a"), await store.grant_resolution(grant_id="old_a")
        unclean, resolution = client.portal.call(resolved)
        assert not unclean and resolution["evidence"]["grant_id"] == "old_a"
    with sqlite3.connect(config.database_path) as db:
        assert json.loads(db.execute("SELECT record FROM sessions").fetchone()[0])["cleanup"] == "UNKNOWN"


def test_offline_resolution_refuses_running_hub_and_held_lease(tmp_path):
    config = settings(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=config)) as client, ready(client=client):
        access = claim(client=client).json()
        evidence = tmp_path / "evidence.json"
        evidence.write_text(json.dumps({"node_id": "node_a", "grant_id": access["grant_id"], "checked_at": datetime.now(UTC).isoformat(), "details": "模拟核查证据"}))
        with pytest.raises(RuntimeError, match="已被 Hub"):
            confirm_cleanup(database_path=config.database_path, grant_id=access["grant_id"], evidence_file=evidence)
    with pytest.raises(ValueError, match="QUARANTINED"):
        confirm_cleanup(database_path=config.database_path, grant_id=access["grant_id"], evidence_file=evidence)
