"""匿名独占租约的认证、并发、空闲、清理和交接验收。"""

import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from functools import partial

import pytest
from fastapi.testclient import TestClient

from runbridge_hub.app import create_app
from test_commands import body
from test_r1 import ENROLLMENT, HUB, IDENTITY, auth, grant, register, settings
from test_sessions import live_session, publish, report


@contextmanager
def ready(*, client):
    register(client=client)
    with client.websocket_connect(url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
        yield control, publish(websocket=control)


def claim(*, client, request_id="claim_a", **values):
    return client.post(url="/v1/nodes/node_a/grants", headers=auth(token=HUB), json={"request_id": request_id, **values})


def status(*, client, access):
    response = client.get(url=f"/v1/grants/{access['grant_id']}", headers=auth(token=access["access_token"]))
    assert response.status_code == 200
    return response.json()


def wait_state(*, client, access, state):
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = status(client=client, access=access)
        if value["state"] == state:
            return value
        time.sleep(0.01)
    raise AssertionError(f"租约未进入 {state}：{value}")


def age(*, client, access, field, seconds):
    client.portal.call(partial(client.app.state.service.store.update_grant,
                               grant_id=access["grant_id"], **{field: (datetime.now(UTC) - timedelta(seconds=seconds)).isoformat()}))


@pytest.mark.parametrize("token", [None, "wrong", IDENTITY, ENROLLMENT])
def test_only_hub_token_can_discover_and_claim(tmp_path, token):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client):
        headers = auth(token=token) if token else {}
        for method, path, data in [("GET", "/v1/pool/nodes", None), ("POST", "/v1/nodes/node_a/grants", {"request_id": "forbidden"})]:
            assert client.request(method=method, url=path, headers=headers, json=data).status_code == 401


def test_pool_is_readonly_and_owner_inspect_keeps_real_free_state(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client):
        pool = client.get(url="/v1/pool/nodes", headers=auth(token=HUB)).json()
        assert pool["nodes"][0]["lease"] == {"state": "UNCLAIMED", "claimable": True}
        access = claim(client=client).json()
        assert access["token_available"] is True
        assert set(access["access_config"]) == {"hub_url", "node_id", "grant_id", "access_token", "expires_at"}
        assert access["access_config"]["hub_url"] == "http://hub.test/runbridge"
        assert access["access_config"]["expires_at"] == access["expires_at"]
        assert 3599 < (datetime.fromisoformat(access["expires_at"]) - datetime.fromisoformat(access["created_at"])).total_seconds() <= 3600
        pool = client.get(url="/v1/pool/nodes", headers=auth(token=HUB)).json()
        assert pool["nodes"][0]["lease"] == {"state": "HELD", "claimable": False}
        assert "token_hash" not in str(pool) and "access_token" not in str(pool)
        view = client.get(url="/v1/nodes/node_a", headers=auth(token=access["access_token"])).json()
        assert view["capabilities"]["resources"][0]["occupancy"] == "FREE"
        for path in ["/v1/nodes/node_a", f"/v1/grants/{access['grant_id']}"]:
            assert client.get(url=path, headers=auth(token=HUB)).status_code == 401
        with sqlite3.connect(client.app.state.service.settings.database_path) as db:
            row = db.execute("SELECT * FROM grants").fetchone()
        assert access["access_token"] not in str(row)


def test_concurrent_claim_and_database_constraint(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client), ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda index: claim(client=client, request_id=f"claim_{index}"), range(8)))
        assert sum(value.status_code == 201 for value in results) == 1
        assert sum(value.status_code == 409 and value.json()["code"] == "NODE_LEASE_BUSY" for value in results) == 7
        with sqlite3.connect(client.app.state.service.settings.database_path) as db:
            with pytest.raises(sqlite3.IntegrityError):
                db.execute("INSERT INTO grants (grant_id,node_id,token_hash,created_at,state) VALUES ('bypass','node_a','another_hash','now','HELD')")


def test_claim_retry_never_returns_token_or_reactivates(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client):
        access = claim(client=client).json()
        repeated = claim(client=client)
        assert repeated.status_code == 200
        assert repeated.json() == {"grant_id": access["grant_id"], "node_id": "node_a", "state": "HELD", "token_available": False}
        assert claim(client=client, lease_seconds=100).json()["code"] == "REQUEST_ID_CONFLICT"
        assert client.delete(url=f"/v1/grants/{access['grant_id']}", headers=auth(token=HUB)).status_code == 401
        assert client.delete(url=f"/v1/grants/{access['grant_id']}", headers=auth(token=access["access_token"])).json()["state"] == "RELEASED"
        assert claim(client=client).json()["state"] == "RELEASED"
        assert claim(client=client, request_id="new_a").status_code == 201


@pytest.mark.parametrize("duration", [0, -1, 1.5, True, "3600", 86401])
def test_lease_duration_is_strict_and_bounded(tmp_path, duration):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client):
        assert claim(client=client, lease_seconds=duration).status_code == 422


def test_configurable_maximum_default_and_idle_snapshot(tmp_path):
    configuration = settings(tmp_path=tmp_path).model_copy(update={"grant_max_lease_seconds": 120, "grant_idle_timeout_seconds": 90})
    with TestClient(app=create_app(settings=configuration)) as client, ready(client=client):
        assert claim(client=client, request_id="over", lease_seconds=121).json()["code"] == "LEASE_TOO_LONG"
        access = claim(client=client).json()
        assert (datetime.fromisoformat(access["expires_at"]) - datetime.fromisoformat(access["created_at"])).total_seconds() == 120
        assert access["idle_timeout_seconds"] == 90
    with TestClient(app=create_app(settings=configuration.model_copy(update={"grant_max_lease_seconds": 90000, "grant_idle_timeout_seconds": 20}))) as client:
        current = status(client=client, access=access)
        assert current["expires_at"] == access["expires_at"] and current["idle_timeout_seconds"] == 90
        renewed = client.post(url=f"/v1/grants/{access['grant_id']}/renew", headers=auth(token=access["access_token"]), json={"lease_seconds": 90000})
        assert renewed.status_code == 200
        assert renewed.json()["last_activity_at"] == access["last_activity_at"]


def test_idle_not_refreshed_by_renew_or_poll_and_per_request_expiry(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client):
        access = claim(client=client).json()
        for _ in range(3):
            assert client.get(url="/v1/nodes/node_a", headers=auth(token=access["access_token"])).status_code == 200
            renewed = client.post(url=f"/v1/grants/{access['grant_id']}/renew", headers=auth(token=access["access_token"]), json={"lease_seconds": 86400}).json()
            assert renewed["last_activity_at"] == access["last_activity_at"]
            assert renewed["idle_deadline_at"] == access["idle_deadline_at"]
        age(client=client, access=access, field="last_activity_at", seconds=601)
        # 不等待维护循环；入口自身必须拒绝已经空闲到期的请求。
        assert client.get(url="/v1/nodes/node_a", headers=auth(token=access["access_token"])).status_code == 401
        closed = wait_state(client=client, access=access, state="RELEASED")
        assert closed["close_reason"] == "IDLE_TIMEOUT"
        assert client.post(url=f"/v1/grants/{access['grant_id']}/renew", headers=auth(token=access["access_token"]), json={}).status_code == 401


@pytest.mark.parametrize("cleanup,expected", [("COMPLETE", "RELEASED"), ("UNKNOWN", "QUARANTINED")])
def test_release_waits_for_cleanup_and_old_token_cannot_affect_next_holder(tmp_path, cleanup, expected):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, control, _, generation):
            path = f"/v1/grants/{access['grant_id']}"
            response = client.delete(url=path, headers=auth(token=access["access_token"]))
            assert response.status_code == 202 and response.json()["state"] == "RELEASING"
            assert claim(client=client, request_id="blocked").json()["code"] == "NODE_LEASE_BUSY"
            assert client.get(url=f"/v2/sessions/{view['session_id']}", headers=auth(token=access["access_token"])).status_code == 401
            assert control.receive_json()["type"] == "session_stop"
            report(control=control, generation=generation, session_id=view["session_id"], type="session_closed", cleanup=cleanup)
            result = wait_state(client=client, access=access, state=expected)
            assert result["cleanup"] == cleanup
            if expected == "RELEASED":
                next_access = claim(client=client, request_id="next_holder").json()
                assert next_access["grant_id"] != access["grant_id"]
                assert client.delete(url=path, headers=auth(token=access["access_token"])).json()["state"] == "RELEASED"
                assert status(client=client, access=next_access)["state"] == "HELD"
                assert client.get(url=f"/v1/grants/{next_access['grant_id']}", headers=auth(token=access["access_token"])).status_code == 403
            else:
                assert claim(client=client, request_id="still_blocked").status_code == 409


def test_real_inflight_suspends_idle_then_completion_restarts_it(tmp_path):
    configuration = settings(tmp_path=tmp_path).model_copy(update={"grant_idle_timeout_seconds": 1})
    with TestClient(app=create_app(settings=configuration)) as client, ThreadPoolExecutor(max_workers=1) as pool:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, _, execution, _):
            running = pool.submit(client.post, url=f"/v2/sessions/{view['session_id']}/commands", headers=auth(token=access["access_token"]), json=body(params={"timeout": 3000}))
            message = execution.receive_json()
            time.sleep(1.1)
            current = status(client=client, access=access)
            assert current["state"] == "HELD" and current["inflight"] and current["idle_deadline_at"] is None
            execution.send_json({"protocol_version": 2, "type": "result", "session_id": view["session_id"], "connection_generation": view["connection_generation"], "request_id": message["request_id"], "status": "SUCCEEDED", "execution_outcome": "COMPLETED", "result": {"kind": "json", "value": "about:blank"}})
            assert running.result(timeout=3).status_code == 200
            current = status(client=client, access=access)
            assert current["state"] == "HELD" and not current["inflight"] and current["idle_deadline_at"] is not None


def test_restart_preserves_quarantine_and_original_unknown(tmp_path):
    configuration = settings(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access, cleanup="UNKNOWN") as (view, *_):
            sid = view["session_id"]
    with TestClient(app=create_app(settings=configuration)) as client, ready(client=client):
        assert wait_state(client=client, access=access, state="QUARANTINED")["cleanup"] == "UNKNOWN"
        assert claim(client=client, request_id="after_restart").json()["code"] == "NODE_LEASE_BUSY"
        async def original():
            return await client.app.state.service.store.session(session_id=sid)
        assert client.portal.call(original)["cleanup"] == "UNKNOWN"


def test_open_ready_session_does_not_keep_idle_lease_alive(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, control, _, generation):
            age(client=client, access=access, field="last_activity_at", seconds=601)
            assert client.get(url=f"/v2/sessions/{view['session_id']}", headers=auth(token=access["access_token"])).status_code == 401
            assert control.receive_json()["type"] == "session_stop"
            report(control=control, generation=generation, session_id=view["session_id"], type="session_closed", cleanup="COMPLETE")
            assert wait_state(client=client, access=access, state="RELEASED")["close_reason"] == "IDLE_TIMEOUT"


def test_claim_checks_all_resources_of_exclusive_node(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ready(client=client) as (control, generation):
        control.send_json({"type": "capabilities", "connection_generation": generation,
                           "capabilities": {"backends": [{"name": "playwright", "runtime_version": "1.63.0", "coverage_status": "SUPPORTED"}],
                                            "resources": [{"resource_id": resource, "backend": "playwright", "kind": "MANAGED_CHROMIUM", "readiness": "READY", "occupancy": occupancy, "methods": ["page.title"]} for resource, occupancy in [("chromium", "FREE"), ("other", "UNKNOWN")]]}})
        assert control.receive_json()["type"] == "capabilities_ack"
        assert claim(client=client).json()["code"] == "NODE_NOT_READY"


def test_worker_session_state_query_does_not_refresh_idle(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ThreadPoolExecutor(max_workers=1) as pool:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, _, execution, _):
            before = status(client=client, access=access)
            request = {"request_id": "state_poll", "method": "runbridge.session_state", "target": {"type": "session", "id": view["session_id"]}, "params": {}}
            result = pool.submit(client.post, url=f"/v2/sessions/{view['session_id']}/commands", headers=auth(token=access["access_token"]), json=request)
            message = execution.receive_json()
            pending = status(client=client, access=access)
            assert pending["last_activity_at"] == before["last_activity_at"] and not pending["inflight"]
            execution.send_json({"protocol_version": 2, "type": "result", "session_id": view["session_id"], "connection_generation": view["connection_generation"], "request_id": message["request_id"], "status": "SUCCEEDED", "execution_outcome": "COMPLETED", "result": {"kind": "json", "value": view["objects"]}})
            assert result.result(timeout=3).status_code == 200
            after = status(client=client, access=access)
            assert after["last_activity_at"] == before["last_activity_at"] and after["idle_deadline_at"] == before["idle_deadline_at"]


def test_claim_retry_keeps_original_record_when_new_claim_policy_changes(tmp_path):
    config = settings(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=config)) as client, ready(client=client):
        access = claim(client=client, lease_seconds=1000).json()
    changed = config.model_copy(update={"grant_max_lease_seconds": 100, "public_url": None})
    with TestClient(app=create_app(settings=changed)) as client:
        repeated = claim(client=client, lease_seconds=1000)
        assert repeated.status_code == 200 and repeated.json()["token_available"] is False
        assert repeated.json()["grant_id"] == access["grant_id"]
        assert status(client=client, access=access)["expires_at"] == access["expires_at"]
        assert client.post(url=f"/v1/grants/{access['grant_id']}/renew", headers=auth(token=access["access_token"]), json={"lease_seconds":1000}).json()["code"] == "LEASE_TOO_LONG"
