"""MCP HTTP 合同与逐请求授权；不启动本机浏览器。"""

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("mcp")
pytest.importorskip("playwright")

from fastapi.testclient import TestClient
from pydantic import ValidationError

from runbridge_hub.app import create_app
from runbridge_hub.browser import BrowserError, BrowserService, BrowserSession
from runbridge_hub.service import ServiceError
from runbridge_hub.settings import HubSettings
from test_r1 import ENROLLMENT, IDENTITY, auth, grant, register, settings


@pytest.fixture
def mcp_client(tmp_path, monkeypatch):
    configuration = settings(tmp_path=tmp_path).model_copy(update={"mcp_enabled": True, "mcp_native_url": "http://127.0.0.1:8787", "mcp_allowed_hosts": ["testserver"]})
    monkeypatch.setattr(BrowserService, "start", AsyncMock())
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        yield client


def rpc(*, client, token: str | None, method: str = "tools/list", params: dict | None = None, protocol: str = "2026-07-28", **headers):
    """发送真实 MCP JSON-RPC 请求，保留 HTTP 认证边界。

    :returns: HTTP 响应。
    """
    values = {"Accept": "application/json, text/event-stream", "Mcp-Protocol-Version": protocol, "Mcp-Method": method, **headers}
    if token is not None:
        values.update(auth(token=token))
    if method == "tools/call":
        values["Mcp-Name"] = params["name"]
    body = dict(params or {})
    if protocol == "2026-07-28":
        body["_meta"] = {"io.modelcontextprotocol/protocolVersion": protocol, "io.modelcontextprotocol/clientCapabilities": {}}
    return client.post(url="/mcp", headers=values, json={"jsonrpc": "2.0", "id": 1, "method": method, "params": body})


def call(*, client, token: str, name: str, arguments: dict, **headers) -> dict:
    response = rpc(client=client, token=token, method="tools/call", params={"name": name, "arguments": arguments}, **headers)
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
def test_discovery_and_scope_work_without_shared_transport_identity(mcp_client, protocol):
    first = grant(client=mcp_client)
    register(client=mcp_client, node_id="node_b")
    second = grant(client=mcp_client, node_id="node_b")
    response = rpc(client=mcp_client, token=first["access_token"], protocol=protocol)
    assert response.status_code == 200, response.text
    tools = response.json()["result"]["tools"]
    assert len(tools) == 12
    assert "access_token" not in str(tools) and "node_token" not in str(tools)
    assert "mcp-session-id" not in response.headers
    own = call(client=mcp_client, token=first["access_token"], name="node_inspect", arguments={"node_id": "node_a"}, protocol=protocol)
    assert own["structuredContent"]["node_id"] == "node_a"
    assert not own.get("isError", False)
    denied = call(client=mcp_client, token=second["access_token"], name="node_inspect", arguments={"node_id": "node_a"}, protocol=protocol)
    assert denied["isError"] and denied["structuredContent"]["code"] == "NODE_OUTSIDE_GRANT"
    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = [pool.submit(call, client=mcp_client, token=access["access_token"], name="node_inspect", arguments={"node_id": access["node_id"]}, protocol=protocol) for access in [first, second] * 3]
        assert [future.result()["structuredContent"]["node_id"] for future in futures] == ["node_a", "node_b"] * 3


def test_revoke_and_expiry_are_checked_on_every_http_request(mcp_client):
    access = grant(client=mcp_client)
    assert rpc(client=mcp_client, token=access["access_token"]).status_code == 200
    assert mcp_client.delete(url=f"/v1/nodes/node_a/grants/{access['grant_id']}", headers=auth(token=IDENTITY)).status_code == 204
    assert rpc(client=mcp_client, token=access["access_token"]).status_code == 401
    expired = grant(client=mcp_client, body={"expires_in_seconds": 0.001})
    time.sleep(0.01)
    assert rpc(client=mcp_client, token=expired["access_token"]).status_code == 401


def test_mcp_host_and_origin_are_not_implicitly_trusted(mcp_client):
    access = grant(client=mcp_client)
    assert rpc(client=mcp_client, token=access["access_token"], Host="untrusted.example").status_code == 421
    assert rpc(client=mcp_client, token=access["access_token"], Origin="https://untrusted.example").status_code == 403
    assert mcp_client.get(url="/health").status_code == 200


def test_invalid_parameters_and_page_urls_do_not_execute(mcp_client):
    access = grant(client=mcp_client)
    for arguments in [{"node_id": "node_a", "lease_seconds": 0}, {"node_id": "node_a", "lease_seconds": 3601}]:
        assert call(client=mcp_client, token=access["access_token"], name="browser_start", arguments=arguments)["isError"]
    denied = call(client=mcp_client, token=access["access_token"], name="browser_navigate", arguments={"session_id": "session_a", "page_id": "page_a", "url": "file:///etc/hosts"})
    assert denied["structuredContent"]["code"] == "INVALID_NAVIGATION_URL"


def test_mcp_defaults_to_disabled_and_validates_internal_address(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        assert client.post(url="/mcp").status_code == 404
    for address in [None, "ws://localhost:8787", "https://user:pass@example.com", "http://localhost/prefix", "http://localhost?token=secret"]:
        with pytest.raises(ValidationError):
            HubSettings(enrollment_token=ENROLLMENT, mcp_enabled=True, mcp_native_url=address)


@pytest.mark.asyncio
async def test_stop_interrupts_inflight_and_queued_operations_without_taking_their_lock():
    view = SimpleNamespace(state="ACTIVE", expires_at=datetime.now(UTC) + timedelta(seconds=60))
    sessions = SimpleNamespace(query=AsyncMock(return_value=view), sessions={})
    service = BrowserService(sessions=sessions, native_url="http://127.0.0.1")
    entry = BrowserSession(session_id="s", node_id="n", grant_id="g")
    page = SimpleNamespace(is_closed=lambda: False)
    entry.pages["p"] = page
    service.entries["s"] = entry
    running = asyncio.Event()
    performed = []

    async def operation():
        try:
            async with service.page(session_id="s", page_id="p", token="test", timeout_ms=30000, mutating=True):
                performed.append(True)
                running.set()
                await asyncio.Event().wait()
        except BrowserError as error:
            return error.code, error.outcome

    first = asyncio.create_task(operation())
    await running.wait()
    queued = asyncio.create_task(operation())
    await asyncio.sleep(0)
    await asyncio.wait_for(service.discard(session_id="s", reason="GRANT_REVOKED"), timeout=1)
    results = await asyncio.wait_for(asyncio.gather(first, queued), timeout=1)
    assert results == [("OPERATION_INTERRUPTED", "OUTCOME_UNKNOWN"), ("OPERATION_INTERRUPTED", "NOT_STARTED")]
    assert len(performed) == 1 and not service.entries
    await service.shutdown()


@pytest.mark.asyncio
async def test_page_scope_and_write_timeout_preserve_outcome():
    view = SimpleNamespace(state="ACTIVE", expires_at=datetime.now(UTC) + timedelta(seconds=60))
    service = BrowserService(sessions=SimpleNamespace(query=AsyncMock(return_value=view)), native_url="http://127.0.0.1")
    entry = BrowserSession(session_id="s", node_id="n", grant_id="g")
    entry.pages["p"] = SimpleNamespace(is_closed=lambda: False)
    service.entries["s"] = entry
    with pytest.raises(BrowserError, match="PAGE_NOT_FOUND"):
        async with service.page(session_id="s", page_id="another_page", token="test", timeout_ms=100):
            pytest.fail("不应执行")
    with pytest.raises(BrowserError) as failure:
        async with service.page(session_id="s", page_id="p", token="test", timeout_ms=5, mutating=True):
            await asyncio.Event().wait()
    assert failure.value.code == "OPERATION_TIMEOUT" and failure.value.outcome == "OUTCOME_UNKNOWN"


@pytest.mark.parametrize("cancel", [False, True])
@pytest.mark.asyncio
async def test_connect_failure_or_cancellation_releases_the_allocated_session(cancel):
    from playwright.async_api import Error

    resource = SimpleNamespace(resource_id="chromium", backend="playwright", kind="MANAGED_CHROMIUM")
    nodes = SimpleNamespace(authorize_access=AsyncMock(return_value={"resource_ids": None}), query=AsyncMock(return_value=SimpleNamespace(connection_status="ONLINE", capabilities=SimpleNamespace(resources=[resource]))))
    created = SimpleNamespace(session_id="s", grant_id="g", native_path="/v1/sessions/s/playwright")
    closed = asyncio.Event()
    session = SimpleNamespace(cleaned=closed)
    sessions = SimpleNamespace(nodes=nodes, create=AsyncMock(return_value=created), sessions={"s": session})
    service = BrowserService(sessions=sessions, native_url="http://127.0.0.1")

    async def close(**kwargs):
        await service.discard(session_id="s", reason=kwargs["reason"])
        closed.set()

    sessions.close = AsyncMock(side_effect=close)
    connecting = asyncio.Event()

    async def connect(**kwargs):
        connecting.set()
        if cancel:
            await asyncio.Event().wait()
        raise Error("不得回显的底层凭据及连接细节")

    service.playwright = SimpleNamespace(chromium=SimpleNamespace(connect=connect), stop=AsyncMock())
    task = asyncio.create_task(service.open(node_id="n", token="test", resource_id="chromium", lease_seconds=30))
    await connecting.wait()
    if cancel:
        task.cancel()
    with pytest.raises(asyncio.CancelledError if cancel else BrowserError) as failure:
        await task
    if not cancel:
        assert failure.value.code == "BROWSER_CONNECT_FAILED"
    assert closed.is_set() and not service.entries
    sessions.close.assert_awaited_once()
    await service.shutdown()


@pytest.mark.asyncio
async def test_permission_is_rechecked_after_waiting_for_session_lock():
    view = SimpleNamespace(state="ACTIVE", expires_at=datetime.now(UTC) + timedelta(seconds=60))
    query = AsyncMock(side_effect=[view, ServiceError(status=401, code="INVALID_ACCESS_TOKEN")])
    service = BrowserService(sessions=SimpleNamespace(query=query), native_url="http://127.0.0.1")
    entry = BrowserSession(session_id="s", node_id="n", grant_id="g")
    entry.pages["p"] = SimpleNamespace(is_closed=lambda: False)
    service.entries["s"] = entry
    await entry.lock.acquire()

    async def operation():
        async with service.page(session_id="s", page_id="p", token="test", timeout_ms=500):
            pytest.fail("许可失效后不得执行排队操作")

    task = asyncio.create_task(operation())
    await asyncio.sleep(0)
    entry.lock.release()
    with pytest.raises(ServiceError, match="INVALID_ACCESS_TOKEN"):
        await task
