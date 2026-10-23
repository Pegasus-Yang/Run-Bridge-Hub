"""只读总览、真实连接状态、资源统计和启动开关验收。"""

import time
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from runbridge_hub.app import create_app
from runbridge_hub.settings import HubSettings
from runbridge_hub.startup import ServeSettings
from runbridge_hub.transport import ControlWebSocketProtocol
from test_r1 import HUB
from test_sessions import publish as publish_execution


ENROLLMENT = "test-enrollment-" + "e" * 48
IDENTITY = "test-node-" + "n" * 48
WEB = "test-web-" + "w" * 48


def configuration(*, tmp_path, **values):
    """建立隔离的总览配置。

    :returns: 当前测试的 Hub 配置。
    """
    return HubSettings(database_path=tmp_path / "hub.sqlite3", enrollment_token=ENROLLMENT, web_token=WEB, hub_token=HUB, public_url="http://hub.test", **values)


def auth(*, token=WEB):
    """构造独立的 Bearer 头。

    :returns: 认证头。
    """
    return {"Authorization": f"Bearer {token}"}


def register(*, client, node_id="node_a", name="真实状态测试节点"):
    """通过正常登记入口创建节点。

    :returns: 登记响应。
    """
    response = client.post(url="/v1/nodes/register", headers=auth(token=ENROLLMENT), json={"node_id": node_id, "name": name, "node_token": IDENTITY})
    assert response.status_code == 201
    return response


def publish(*, websocket):
    """上报包含空闲、忙碌、未就绪和未知资源的测试快照。

    :returns: 当前连接代次。
    """
    welcome = websocket.receive_json()
    generation = welcome["connection_generation"]
    websocket.send_json({
        "protocol_version": 2, "type": "capabilities", "connection_generation": generation,
        "capabilities": {
            "host": {"hostname": "test-host", "platform": "Linux", "machine": "x86_64"},
            "backends": [{"name": "playwright", "coverage_status": "SUPPORTED"}, {"name": "appium", "installed": True}],
            "resources": [
                {"resource_id": name, "backend": "playwright", "kind": "BROWSER", "readiness": readiness, "occupancy": occupancy}
                for name, readiness, occupancy in [
                    ("free", "READY", "FREE"), ("reserved", "READY", "FREE"),
                    ("busy", "READY", "BUSY"), ("unready", "NEEDS_AUTHORIZATION", "FREE"),
                    ("unknown", "READY", "UNKNOWN"),
                ]
            ],
        },
    })
    assert websocket.receive_json()["type"] == "capabilities_ack"
    return generation


def overview(*, client):
    """读取受保护的总览结果。

    :returns: JSON 节点总览。
    """
    response = client.get(url="/dashboard/api/nodes", headers=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    return response.json()


def test_default_web_token_is_private_persistent_and_separate(tmp_path):
    settings = HubSettings(database_path=tmp_path / "hub.sqlite3", enrollment_token=ENROLLMENT)
    assert settings.web_enabled is True
    with TestClient(app=create_app(settings=settings)) as client:
        path = tmp_path / "web.token"
        value = path.read_text().strip()
        assert len(value) >= 32
        assert value != ENROLLMENT
        assert path.stat().st_mode & 0o777 == 0o600
        assert client.get(url="/dashboard/api/nodes", headers=auth(token=value)).status_code == 200
        assert client.get(url="/dashboard").status_code == 200
    with TestClient(app=create_app(settings=settings)) as client:
        assert path.read_text().strip() == value
        assert client.get(url="/dashboard/api/nodes", headers=auth(token=value)).status_code == 200


@pytest.mark.parametrize("path", ["/dashboard", "/dashboard/", "/dashboard/api/nodes", "/dashboard/assets/dashboard.js"])
def test_disabling_web_removes_every_web_route(tmp_path, path):
    with TestClient(app=create_app(settings=configuration(tmp_path=tmp_path, web_enabled=False))) as client:
        assert client.get(url=path, headers=auth()).status_code == 404
        assert client.get(url="/health").status_code == 200
    assert not (tmp_path / "web.token").exists()


def test_only_web_token_can_read_all_nodes_and_it_cannot_write(tmp_path):
    with TestClient(app=create_app(settings=configuration(tmp_path=tmp_path))) as client:
        register(client=client, name="<script>should-not-run</script>")
        with client.websocket_connect(url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            publish_execution(websocket=control)
            grant = client.post(url="/v1/nodes/node_a/grants", headers=auth(token=HUB), json={"request_id": "dashboard_claim"}).json()
        for token in [None, "wrong", ENROLLMENT, IDENTITY, grant["access_token"]]:
            response = client.get(url="/dashboard/api/nodes", headers=auth(token=token) if token else {})
            assert response.status_code == 401
            assert response.json() == {"code": "INVALID_WEB_TOKEN"}
        result = overview(client=client)
        assert result["nodes"][0]["name"] == "<script>should-not-run</script>"
        serialized = str(result)
        for secret in [ENROLLMENT, IDENTITY, WEB, grant["access_token"], "token_hash", "grant_id"]:
            assert secret not in serialized
        assert client.post(url="/v1/nodes/register", headers=auth(), json={"node_id": "node_b", "name": "B", "node_token": IDENTITY}).status_code == 401
        assert client.post(url="/v1/nodes/node_a/grants", headers=auth(), json={"request_id": "forbidden"}).status_code == 401
        assert client.post(url="/v2/nodes/node_a/sessions", headers=auth(), json={"resource_id": "free"}).status_code == 401
        assert client.post(url="/dashboard/api/nodes", headers=auth()).status_code == 405


def test_empty_snapshot_and_bundled_assets(tmp_path):
    with TestClient(app=create_app(settings=configuration(tmp_path=tmp_path))) as client:
        result = overview(client=client)
        assert result["total"] == result["online"] == result["offline"] == 0
        assert result["nodes"] == []
        assert result["resources"] == {"total": 0, "available": 0, "busy": 0, "unknown": 0, "unavailable": 0}
        page = client.get(url="/dashboard")
        assert "节点总览" in page.text
        assert "frame-ancestors 'none'" in page.headers["content-security-policy"]
        for file in ["dashboard.js", "dashboard.css", "icons/magnifying-glass.svg", "icons/arrows-clockwise.svg", "icons/lock-simple.svg", "icons/sign-out.svg", "icons/caret-right.svg", "icons/x.svg"]:
            assert client.get(url=f"/dashboard/assets/{file}").status_code == 200


@pytest.mark.parametrize("enabled", [True, False])
def test_dashboard_switch_coexists_with_mcp_mount(tmp_path, enabled):
    """总览路由优先于 MCP 根挂载，关闭后不会借用 MCP 口令。"""
    pytest.importorskip("mcp")
    settings = configuration(tmp_path=tmp_path, web_enabled=enabled, mcp_enabled=True)
    with TestClient(app=create_app(settings=settings), base_url="http://localhost") as client:
        assert client.get(url="/dashboard").status_code == (200 if enabled else 404)
        assert client.get(url="/dashboard/assets/dashboard.css").status_code == (200 if enabled else 404)
        assert client.get(url="/dashboard/api/nodes", headers=auth()).status_code == (200 if enabled else 404)
        assert client.get(url="/health").status_code == 200


def test_resource_reservations_preparing_disconnect_and_restart(tmp_path):
    settings = configuration(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=settings)) as client:
        register(client=client)
        register(client=client, node_id="node_offline")
        with client.websocket_connect(url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)) as websocket:
            assert overview(client=client)["preparing"] == 1
            publish(websocket=websocket)

            async def reserve():
                async with client.app.state.service.lock:
                    client.app.state.service.reservations[("node_a", "reserved")] = "session_pending"

            client.portal.call(reserve)
            data = overview(client=client)
            assert data["online"] == data["offline"] == 1
            node = next(node for node in data["nodes"] if node["node_id"] == "node_a")
            assert node["resources"] == {"total": 5, "available": 1, "busy": 2, "unknown": 1, "unavailable": 1}
            assert data["resources"] == node["resources"]
            assert node["latency"]["status"] == "UNAVAILABLE"
            assert node["latency"]["rtt_ms"] is None
            assert node["capabilities"]["backends"][1]["coverage_status"] == "NOT_IMPLEMENTED"
        deadline = time.monotonic() + 2
        while True:
            data = overview(client=client)
            if data["online"] == 0:
                break
            assert time.monotonic() < deadline
            time.sleep(0.01)
        node = next(node for node in data["nodes"] if node["node_id"] == "node_a")
        assert node["capabilities_stale"] is True
        assert node["resources"]["unknown"] == 5
        assert node["resources"]["busy"] == node["resources"]["available"] == 0
        assert node["latency"] == {"status": "OFFLINE", "rtt_ms": None, "measured_at": None, "sample_age_ms": None}
    with TestClient(app=create_app(settings=settings)) as client:
        data = overview(client=client)
        assert data["offline"] == 2
        assert data["resources"]["total"] == 0
        assert any(node["capabilities"] for node in data["nodes"])


def test_heartbeat_timeout_does_not_show_live_resources(tmp_path):
    settings = configuration(tmp_path=tmp_path, heartbeat_interval_seconds=0.02, heartbeat_timeout_seconds=0.1)
    with TestClient(app=create_app(settings=settings)) as client:
        register(client=client)
        with client.websocket_connect(url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)) as websocket:
            publish(websocket=websocket)
            time.sleep(0.15)
            data = overview(client=client)
            assert data["offline"] == 1
            assert data["resources"]["available"] == 0


def test_web_token_yaml_paths_environment_priority_and_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("RUNBRIDGE_ENROLLMENT_TOKEN", ENROLLMENT)
    monkeypatch.setenv("RUNBRIDGE_WEB_TOKEN", "env-web-" + "q" * 48)
    (tmp_path / "readonly.token").write_text(WEB, encoding="utf-8")
    path = tmp_path / "hub.yaml"
    path.write_text("web_token_file: readonly.token\n", encoding="utf-8")
    settings = ServeSettings.load(path=path)
    assert settings.web_token_file == tmp_path / "readonly.token"
    assert settings.hub_settings().web_token.get_secret_value() == WEB
    assert ServeSettings().hub_settings().web_token.get_secret_value().startswith("env-web-")
    with pytest.raises(FileNotFoundError):
        ServeSettings(web_token_file=tmp_path / "absent").hub_settings()
    assert ServeSettings(web_enabled=False, web_token_file=tmp_path / "absent").hub_settings().web_token is None


@pytest.mark.parametrize("value", ["", "short", "x" * 257, ENROLLMENT])
def test_invalid_or_reused_web_token_is_rejected(tmp_path, monkeypatch, value):
    monkeypatch.setenv("RUNBRIDGE_ENROLLMENT_TOKEN", ENROLLMENT)
    monkeypatch.setenv("RUNBRIDGE_WEB_TOKEN", value)
    with pytest.raises((ValueError, ValidationError)):
        ServeSettings().hub_settings()


def test_rtt_never_invents_zero_and_expires_with_monotonic_clock(monkeypatch):
    protocol = object.__new__(ControlWebSocketProtocol)
    protocol._rtt_sample = None
    assert protocol.read_rtt()["rtt_ms"] is None
    assert protocol.read_rtt()["status"] == "PENDING"
    observed = datetime.now(UTC) - timedelta(seconds=20)
    protocol._rtt_sample = (23.4567, observed, 100)
    monkeypatch.setattr("runbridge_hub.transport.time.monotonic", lambda: 120)
    assert protocol.read_rtt() == {"status": "MEASURED", "rtt_ms": 23.457, "measured_at": observed, "sample_age_ms": 20000}
    monkeypatch.setattr("runbridge_hub.transport.time.monotonic", lambda: 161)
    assert protocol.read_rtt()["status"] == "STALE"
    assert protocol.read_rtt()["rtt_ms"] is None
