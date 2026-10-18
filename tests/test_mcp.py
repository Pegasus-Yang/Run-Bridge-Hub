"""MCP HTTP 合同与逐请求授权；不启动本机浏览器。"""

import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("mcp")

from fastapi.testclient import TestClient

from runbridge_hub.app import create_app
from runbridge_hub.browser import BrowserService
from test_r1 import ENROLLMENT, IDENTITY, auth, grant, register, settings


@pytest.fixture
def mcp_client(tmp_path, monkeypatch):
    configuration = settings(tmp_path=tmp_path).model_copy(
        update={"mcp_enabled": True, "mcp_allowed_hosts": ["testserver"]}
    )
    monkeypatch.setattr(BrowserService, "start", AsyncMock())
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        yield client


def rpc(
    *,
    client,
    token: str | None,
    method: str = "tools/list",
    params: dict | None = None,
    protocol: str = "2026-07-28",
    **headers,
):
    """发送真实 MCP JSON-RPC 请求，保留 HTTP 认证边界。

    :returns: HTTP 响应。
    """
    values = {
        "Accept": "application/json, text/event-stream",
        "Mcp-Protocol-Version": protocol,
        "Mcp-Method": method,
        **headers,
    }
    if token is not None:
        values.update(auth(token=token))
    if method == "tools/call":
        values["Mcp-Name"] = params["name"]
    body = dict(params or {})
    if protocol == "2026-07-28":
        body["_meta"] = {
            "io.modelcontextprotocol/protocolVersion": protocol,
            "io.modelcontextprotocol/clientCapabilities": {},
        }
    return client.post(
        url="/mcp",
        headers=values,
        json={"jsonrpc": "2.0", "id": 1, "method": method, "params": body},
    )


def call(*, client, token: str, name: str, arguments: dict, **headers) -> dict:
    response = rpc(
        client=client,
        token=token,
        method="tools/call",
        params={"name": name, "arguments": arguments},
        **headers,
    )
    assert response.status_code == 200, response.text
    return response.json()["result"]


@pytest.mark.parametrize("token", [None, "invalid", IDENTITY, ENROLLMENT])
def test_mcp_rejects_non_access_credentials(mcp_client, token):
    response = rpc(client=mcp_client, token=token)
    assert response.status_code == 401
    assert response.json() == {"code": "INVALID_ACCESS_TOKEN"}
    assert response.headers["WWW-Authenticate"] == "Bearer"
    if token:
        assert token not in response.text


@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
def test_discovery_and_scope_work_without_shared_transport_identity(
    mcp_client, protocol
):
    first = grant(client=mcp_client)
    register(client=mcp_client, node_id="node_b")
    second = grant(client=mcp_client, node_id="node_b")
    response = rpc(client=mcp_client, token=first["access_token"], protocol=protocol)
    assert response.status_code == 200, response.text
    tools = response.json()["result"]["tools"]
    assert len(tools) == 27
    assert "access_token" not in str(tools) and "node_token" not in str(tools)
    assert "mcp-session-id" not in response.headers
    own = call(
        client=mcp_client,
        token=first["access_token"],
        name="node_inspect",
        arguments={"node_id": "node_a"},
        protocol=protocol,
    )
    assert own["structuredContent"]["node_id"] == "node_a"
    assert not own.get("isError", False)
    denied = call(
        client=mcp_client,
        token=second["access_token"],
        name="node_inspect",
        arguments={"node_id": "node_a"},
        protocol=protocol,
    )
    assert (
        denied["isError"]
        and denied["structuredContent"]["code"] == "NODE_OUTSIDE_GRANT"
    )
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [
            pool.submit(
                call,
                client=mcp_client,
                token=access["access_token"],
                name="node_inspect",
                arguments={"node_id": access["node_id"]},
                protocol=protocol,
            )
            for access in [first, second] * 3
        ]
        assert [
            future.result()["structuredContent"]["node_id"] for future in futures
        ] == ["node_a", "node_b"] * 3


def test_revoke_and_expiry_are_checked_on_every_http_request(mcp_client):
    access = grant(client=mcp_client)
    assert rpc(client=mcp_client, token=access["access_token"]).status_code == 200
    assert (
        mcp_client.delete(
            url=f"/v1/nodes/node_a/grants/{access['grant_id']}",
            headers=auth(token=IDENTITY),
        ).status_code
        == 204
    )
    assert rpc(client=mcp_client, token=access["access_token"]).status_code == 401
    expired = grant(client=mcp_client, body={"expires_in_seconds": 0.001})
    time.sleep(0.01)
    assert rpc(client=mcp_client, token=expired["access_token"]).status_code == 401


def test_mcp_host_and_origin_are_not_implicitly_trusted(mcp_client):
    access = grant(client=mcp_client)
    assert (
        rpc(
            client=mcp_client, token=access["access_token"], Host="untrusted.example"
        ).status_code
        == 421
    )
    assert (
        rpc(
            client=mcp_client,
            token=access["access_token"],
            Origin="https://untrusted.example",
        ).status_code
        == 403
    )
    assert mcp_client.get(url="/health").status_code == 200


def test_invalid_parameters_and_page_urls_do_not_execute(mcp_client):
    access = grant(client=mcp_client)
    for arguments in [
        {"node_id": "node_a", "lease_seconds": 0},
        {"node_id": "node_a", "lease_seconds": 3601},
    ]:
        assert call(
            client=mcp_client,
            token=access["access_token"],
            name="browser_start",
            arguments=arguments,
        )["isError"]
    denied = call(
        client=mcp_client,
        token=access["access_token"],
        name="browser_navigate",
        arguments={
            "session_id": "session_a",
            "page_id": "page_a",
            "url": "file:///etc/hosts",
        },
    )
    assert denied["structuredContent"]["code"] == "SESSION_NOT_FOUND"


def test_mcp_defaults_to_disabled(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        assert client.post(url="/mcp").status_code == 404


async def test_failed_start_returns_original_id_for_recovery():
    from types import SimpleNamespace
    from runbridge_hub.browser import BrowserError
    from runbridge_hub.service import ServiceError

    resource = SimpleNamespace(
        kind="MANAGED_CHROMIUM", tool="playwright", resource_id="chromium"
    )
    nodes = SimpleNamespace(
        authorize_access=AsyncMock(
            return_value={"grant_id": "grant_a", "resource_ids": None}
        ),
        query=AsyncMock(
            return_value=SimpleNamespace(
                capabilities=SimpleNamespace(resources=[resource])
            )
        ),
        store=SimpleNamespace(
            mcp_request=AsyncMock(
                return_value={
                    "session_id": "session_a",
                    "execution_outcome": "OUTCOME_UNKNOWN",
                }
            )
        ),
    )
    sessions = SimpleNamespace(
        nodes=nodes,
        create=AsyncMock(
            side_effect=ServiceError(status=504, code="SESSION_PREPARE_FAILED")
        ),
    )
    service = BrowserService(sessions=sessions, commands=None, visual=None)
    with pytest.raises(BrowserError) as caught:
        await service.open(node_id="node_a", token="test", request_id="open_known")
    assert caught.value.request_id == "open_known"
    assert caught.value.outcome == "OUTCOME_UNKNOWN"
