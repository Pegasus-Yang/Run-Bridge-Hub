"""登记、许可隔离、控制生命周期和重启持久化验收。"""

import sqlite3
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from runbridge_hub.app import create_app
from runbridge_hub.settings import HubSettings


ENROLLMENT = "test-enrollment-" + "e" * 40
IDENTITY = "test-identity-" + "n" * 40


def auth(*, token: str) -> dict:
    """构造测试认证头。

    :returns: Bearer 头。
    """
    return {"Authorization": f"Bearer {token}"}


def settings(*, tmp_path: Path, timeout: float = 3) -> HubSettings:
    """为测试建立独立数据库。

    :returns: Hub 配置。
    """
    return HubSettings(
        database_path=tmp_path / "hub.sqlite3",
        enrollment_token=ENROLLMENT,
        heartbeat_interval_seconds=0.025,
        heartbeat_timeout_seconds=timeout,
    )


def register(
    *, client: TestClient, node_id: str = "node_a", token: str = IDENTITY
) -> dict:
    """登记测试身份。

    :returns: 登记结果。
    """
    response = client.post(
        url="/v1/nodes/register",
        headers=auth(token=ENROLLMENT),
        json={"node_id": node_id, "name": node_id, "node_token": token},
    )
    assert response.status_code in {200, 201}
    return response.json()


def grant(
    *, client: TestClient, node_id: str = "node_a", body: dict | None = None
) -> dict:
    """签发测试查询许可。

    :returns: 新许可。
    """
    response = client.post(
        url=f"/v1/nodes/{node_id}/grants", headers=auth(token=IDENTITY), json=body or {}
    )
    assert response.status_code == 201
    return response.json()


def publish(*, websocket, resources: list | None = None) -> int:
    """用测试资源快照完成控制握手，不代表真机探测。

    :returns: 连接代次。
    """
    welcome = websocket.receive_json()
    generation = welcome["connection_generation"]
    websocket.send_json(
        {
            "protocol_version": 2,
            "type": "capabilities",
            "connection_generation": generation,
            "capabilities": {
                "host": {"test_fixture": "simulated"},
                "backends": [{"name": "playwright"}],
                "resources": resources or [],
            },
        }
    )
    assert websocket.receive_json()["type"] == "capabilities_ack"
    return generation


def wait_offline(*, client: TestClient, token: str) -> dict:
    """等待连接清理完成。

    :returns: 离线视图。
    """
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        view = client.get(url="/v1/nodes/node_a", headers=auth(token=token)).json()
        if view["connection_status"] == "OFFLINE":
            return view
        time.sleep(0.01)
    raise AssertionError("节点未按预期离线")


@pytest.mark.parametrize("token", [None, "incorrect"])
def test_registration_requires_enrollment(tmp_path, token):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        response = client.post(
            url="/v1/nodes/register",
            headers=auth(token=token) if token else {},
            json={"node_id": "node_a", "name": "A", "node_token": IDENTITY},
        )
        assert response.status_code == 401


def test_registration_is_idempotent_and_cannot_overwrite(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        assert register(client=client)["created"] is True
        assert register(client=client)["created"] is False
        other = "other-node-secret-" + "x" * 40
        response = client.post(
            url="/v1/nodes/register",
            headers=auth(token=ENROLLMENT),
            json={"node_id": "node_a", "name": "attacker", "node_token": other},
        )
        assert response.status_code == 409
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            assert websocket.receive_json()["node_id"] == "node_a"


def test_validation_does_not_echo_secret_input(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        secret = "private-invalid-secret"
        response = client.post(
            url="/v1/nodes/register",
            headers=auth(token=ENROLLMENT),
            json={"node_id": "node_a", "name": "A", "node_token": secret},
        )
        assert response.status_code == 422
        if secret in response.text:
            raise AssertionError("校验响应回显了秘密，内容已隐藏")
        assert "input" not in response.text


def test_identity_and_caller_grants_have_separate_roles(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        register(client=client, node_id="node_b")
        permit = grant(client=client)
        assert (
            client.get(url="/v1/nodes/node_a", headers=auth(token=IDENTITY)).status_code
            == 401
        )
        assert (
            client.get(
                url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
            ).status_code
            == 200
        )
        assert (
            client.get(
                url="/v1/nodes/node_b", headers=auth(token=permit["access_token"])
            ).status_code
            == 403
        )
        assert (
            client.post(
                url="/v1/nodes/node_a/grants",
                headers=auth(token=permit["access_token"]),
                json={},
            ).status_code
            == 401
        )
        listed = client.get(
            url="/v1/nodes/node_a/grants", headers=auth(token=IDENTITY)
        ).json()
        assert "access_token" not in listed[0] and "token_hash" not in listed[0]
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(
                url="/v2/nodes/node_a/control",
                headers=auth(token=permit["access_token"]),
            ):
                pass


def test_resource_scope_filters_capabilities(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        permit = grant(client=client, body={"resource_ids": ["browser_a"]})
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            publish(
                websocket=websocket,
                resources=[
                    {"resource_id": name, "backend": "playwright", "kind": "BROWSER"}
                    for name in ["browser_a", "browser_b"]
                ],
            )
            view = client.get(
                url="/v1/nodes/node_a/capabilities",
                headers=auth(token=permit["access_token"]),
            ).json()
            assert [
                item["resource_id"] for item in view["capabilities"]["resources"]
            ] == ["browser_a"]
            assert view["capabilities"]["resources"][0]["readiness"] == "NEEDS_PROBE"


def test_grant_expiry_is_enforced(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        permit = grant(client=client, body={"expires_in_seconds": 0.05})
        time.sleep(0.08)
        assert (
            client.get(
                url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
            ).status_code
            == 401
        )


def test_heartbeat_query_and_restart_snapshot(tmp_path):
    configuration = settings(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        permit = grant(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            generation = publish(websocket=websocket)
            with sqlite3.connect(database=configuration.database_path) as database:
                before = database.execute("SELECT last_seen_at FROM nodes").fetchone()[
                    0
                ]
            websocket.send_json(
                {
                    "protocol_version": 2,
                    "type": "heartbeat",
                    "connection_generation": generation,
                }
            )
            acknowledgement = websocket.receive_json()
            assert acknowledgement["heartbeat_count"] == 1
            with sqlite3.connect(database=configuration.database_path) as database:
                after = database.execute("SELECT last_seen_at FROM nodes").fetchone()[0]
            assert after == before
            view = client.get(
                url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
            ).json()
            assert view["connection_status"] == "ONLINE"
            assert view["capabilities_stale"] is False
            assert view["observation_age_ms"] >= 0
        assert (
            wait_offline(client=client, token=permit["access_token"])[
                "capabilities_stale"
            ]
            is True
        )
    with TestClient(app=create_app(settings=configuration)) as restarted:
        view = restarted.get(
            url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
        ).json()
        assert view["connection_status"] == "OFFLINE"
        assert view["capabilities"]["host"]["test_fixture"] == "simulated"
        with restarted.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            assert publish(websocket=websocket) > generation


def test_revocation_survives_restart(tmp_path):
    configuration = settings(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        permit = grant(client=client)
        assert (
            client.delete(
                url=f"/v1/nodes/node_a/grants/{permit['grant_id']}",
                headers=auth(token=IDENTITY),
            ).status_code
            == 204
        )
        assert (
            client.get(
                url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
            ).status_code
            == 401
        )
    with TestClient(app=create_app(settings=configuration)) as restarted:
        assert (
            restarted.get(
                url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
            ).status_code
            == 401
        )


def test_missing_heartbeat_marks_node_offline(tmp_path):
    with TestClient(
        app=create_app(settings=settings(tmp_path=tmp_path, timeout=0.15))
    ) as client:
        register(client=client)
        permit = grant(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            publish(websocket=websocket)
            assert (
                wait_offline(client=client, token=permit["access_token"])[
                    "capabilities_stale"
                ]
                is True
            )


def test_old_connection_cleanup_cannot_remove_replacement(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        permit = grant(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as first:
            old = publish(websocket=first)
            with client.websocket_connect(
                url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
            ) as second:
                current = publish(websocket=second)
                assert current > old
                with pytest.raises(WebSocketDisconnect) as closed:
                    first.receive_json()
                assert closed.value.code == 4001
                view = client.get(
                    url="/v1/nodes/node_a", headers=auth(token=permit["access_token"])
                ).json()
                assert view["connection_status"] == "ONLINE"
                assert view["connection_generation"] == current
                second.send_json(
                    {
                        "protocol_version": 2,
                        "type": "heartbeat",
                        "connection_generation": current,
                    }
                )
                assert second.receive_json()["heartbeat_count"] == 1


@pytest.mark.parametrize(
    "message",
    [
        {"protocol_version": 1, "type": "heartbeat", "connection_generation": 1},
        {
            "protocol_version": 2,
            "type": "heartbeat",
            "connection_generation": 1,
            "unexpected": True,
        },
    ],
)
def test_protocol_version_and_unknown_fields_are_rejected(tmp_path, message):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            publish(websocket=websocket)
            websocket.send_json(message)
            assert websocket.receive_json()["code"] == "INVALID_CONTROL_MESSAGE"
            with pytest.raises(WebSocketDisconnect) as closed:
                websocket.receive_json()
            assert closed.value.code == 1008


def test_stale_generation_is_rejected(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as websocket:
            generation = publish(websocket=websocket)
            websocket.send_json(
                {
                    "protocol_version": 2,
                    "type": "heartbeat",
                    "connection_generation": generation + 1,
                }
            )
            assert websocket.receive_json()["code"] == "STALE_CONNECTION"
