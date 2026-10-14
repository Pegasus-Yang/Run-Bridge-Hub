"""会话合同、原生帧类型和资源占用的管理层验收。"""

import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse

from runbridge_hub.app import create_app
from test_r1 import IDENTITY, auth, grant, register, settings


def publish(*, websocket, readiness: str = "READY", occupancy: str = "FREE") -> int:
    """上报模拟的执行资源；真实浏览器另由 Node SDK 验收。

    :returns: 当前连接代次。
    """
    welcome = websocket.receive_json()
    generation = welcome["connection_generation"]
    websocket.send_json({"type": "capabilities", "connection_generation": generation, "capabilities": {"backends": [{"name": "playwright", "installed": True, "runtime_version": "1.63.0", "coverage_status": "SUPPORTED"}], "resources": [{"resource_id": "chromium", "backend": "playwright", "kind": "MANAGED_CHROMIUM", "readiness": readiness, "occupancy": occupancy}]}})
    assert websocket.receive_json()["type"] == "capabilities_ack"
    return generation


def report(*, control, generation: int, session_id: str, type: str, **values):
    """发送当前代次的模拟节点确认。"""
    control.send_json({"type": type, "connection_generation": generation, "session_id": session_id, **values})
    assert control.receive_json()["type"] == "session_ack"


@pytest.mark.parametrize("readiness,occupancy,expected", [("UNAVAILABLE", "FREE", "RESOURCE_NOT_READY"), ("READY", "BUSY", "RESOURCE_BUSY")])
def test_resource_must_be_ready_and_free(tmp_path, readiness, occupancy, expected):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            publish(websocket=control, readiness=readiness, occupancy=occupancy)
            response = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium", "client_version": "1.63.0"})
            assert response.status_code == 409 and response.json()["code"] == expected


def test_resource_scope_and_protocol_version_are_checked(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        limited = grant(client=client, body={"resource_ids": ["other_resource"]})
        access = grant(client=client)
        with client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            publish(websocket=control)
            denied = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=limited["access_token"]), json={"resource_id": "chromium", "client_version": "1.63.0"})
            assert denied.status_code == 403 and denied.json()["code"] == "RESOURCE_OUTSIDE_GRANT"
            mismatch = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium", "client_version": "1.62.0"})
            assert mismatch.status_code == 428
            offline = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "missing", "client_version": "1.63.0"})
            assert offline.status_code == 404


def test_native_frames_remain_typed_ordered_and_isolated(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ThreadPoolExecutor(max_workers=1) as pool:
        register(client=client)
        access = grant(client=client)
        other = grant(client=client)
        with client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            generation = publish(websocket=control)
            future = pool.submit(client.post, url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium", "client_version": "1.63.0"})
            opened = control.receive_json()
            session_id = opened["session_id"]
            racing = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium", "client_version": "1.63.0"})
            assert racing.status_code == 409 and racing.json()["code"] == "RESOURCE_BUSY"
            tunnel_url = f"/v1/nodes/node_a/sessions/{session_id}/tunnel"
            with client.websocket_connect(url=tunnel_url, headers={**auth(token=IDENTITY), "x-runbridge-generation": str(generation)}) as tunnel:
                report(control=control, generation=generation, session_id=session_id, type="session_prepared", runtime_version="1.63.0")
                result = future.result(timeout=3)
                assert result.status_code == 201
                native_path = result.json()["native_path"]
                for token, status in [("invalid", 401), (other["access_token"], 403)]:
                    with pytest.raises(WebSocketDenialResponse) as denied:
                        with client.websocket_connect(url=native_path, headers={**auth(token=token), "User-Agent": "Playwright/1.63.0"}):
                            pass
                    assert denied.value.status_code == status
                with pytest.raises(WebSocketDenialResponse) as mismatch:
                    with client.websocket_connect(url=native_path, headers={**auth(token=access["access_token"]), "User-Agent": "Playwright/1.62.0"}):
                        pass
                assert mismatch.value.status_code == 428
                with client.websocket_connect(url=native_path, headers={**auth(token=access["access_token"]), "User-Agent": "Playwright/1.63.0", "x-playwright-browser": "chromium"}) as caller:
                    activated = control.receive_json()
                    assert activated["type"] == "session_connect"
                    assert activated["headers"]["x-playwright-browser"] == "chromium"
                    assert "authorization" not in activated["headers"]
                    data = bytes(range(256)) * 8192
                    caller.send_bytes(data=data)
                    assert tunnel.receive_bytes() == data
                    tunnel.send_text(data='{"native": "response", "unknown_parameter": true}')
                    assert caller.receive_text() == '{"native": "response", "unknown_parameter": true}'
                    tunnel.send_bytes(data=data)
                    assert caller.receive_bytes() == data
                    for number in range(3):
                        caller.send_text(data=f"ordered-{number}")
                        assert tunnel.receive_text() == f"ordered-{number}"
                    with pytest.raises(WebSocketDenialResponse) as duplicate:
                        with client.websocket_connect(url=native_path, headers={**auth(token=access["access_token"]), "User-Agent": "Playwright/1.63.0"}):
                            pass
                    assert duplicate.value.status_code == 409
                    caller.close()
                    stopped = control.receive_json()
                    assert stopped["type"] == "session_stop"
                    report(control=control, generation=generation, session_id=session_id, type="session_closed", cleanup="COMPLETE")
                    closed = client.get(url=f"/v1/sessions/{session_id}", headers=auth(token=access["access_token"])).json()
                    assert closed["state"] == "CLOSED" and closed["cleanup"] == "COMPLETE"
                    assert closed["execution_outcome"] == "OUTCOME_UNKNOWN"


def test_unknown_cleanup_does_not_release_resource(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ThreadPoolExecutor(max_workers=1) as pool:
        register(client=client)
        access = grant(client=client)
        with client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            generation = publish(websocket=control)
            future = pool.submit(client.post, url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium", "client_version": "1.63.0"})
            session_id = control.receive_json()["session_id"]
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{session_id}/tunnel", headers={**auth(token=IDENTITY), "x-runbridge-generation": str(generation)}):
                report(control=control, generation=generation, session_id=session_id, type="session_prepared", runtime_version="1.63.0")
                assert future.result(timeout=3).status_code == 201
                releasing = pool.submit(client.delete, url=f"/v1/sessions/{session_id}", headers=auth(token=access["access_token"]))
                assert control.receive_json()["type"] == "session_stop"
                report(control=control, generation=generation, session_id=session_id, type="session_closed", cleanup="UNKNOWN")
                assert releasing.result(timeout=3).json()["cleanup"] == "UNKNOWN"
                again = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium", "client_version": "1.63.0"})
                assert again.status_code == 409 and again.json()["code"] == "RESOURCE_BUSY"


def test_schema_one_migrates_without_losing_node_identity(tmp_path):
    configuration = settings(tmp_path=tmp_path)
    with sqlite3.connect(database=configuration.database_path) as database:
        database.executescript("CREATE TABLE nodes (node_id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0, capabilities TEXT, capabilities_observed_at TEXT, last_seen_at TEXT); CREATE TABLE grants (grant_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(node_id), token_hash TEXT NOT NULL UNIQUE, resource_ids TEXT, created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT); PRAGMA user_version=1;")
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        assert register(client=client)["created"] is False
    with sqlite3.connect(database=configuration.database_path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 3
        assert database.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0


@pytest.mark.parametrize("scope,version,status,code", [(None, "1.63.0", 409, "RESOURCE_NOT_AUTHORIZED"), ("BROWSER_INSTANCE", "1.59.0", 428, "CDP_CLIENT_VERSION_UNSUPPORTED")])
def test_borrowed_chrome_requires_instance_authorization_and_supported_client(tmp_path, scope, version, status, code):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            generation = control.receive_json()["connection_generation"]
            control.send_json({"type": "capabilities", "connection_generation": generation, "capabilities": {"backends": [{"name": "chrome-cdp", "runtime_version": "154.0.8037.99", "coverage_status": "SUPPORTED"}], "resources": [{"resource_id": "chrome", "backend": "chrome-cdp", "kind": "BORROWED_CHROME_CDP", "readiness": "READY", "occupancy": "FREE", "authorization_scope": scope}]}})
            assert control.receive_json()["type"] == "capabilities_ack"
            response = client.post(url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chrome", "client_version": version})
            assert response.status_code == status and response.json()["code"] == code
