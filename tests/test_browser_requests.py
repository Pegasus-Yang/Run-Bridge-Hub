"""真实 SQLite 与会话服务验证 MCP 请求恢复，不启动浏览器。"""

import asyncio
import gc
import sqlite3
import weakref
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from pydantic import SecretStr

pytest.importorskip("mcp")
pytest.importorskip("playwright")
from playwright.async_api import Error

from runbridge_hub.browser import BrowserError, BrowserService
from runbridge_hub.mcp_server import REQUEST_TOKEN
from runbridge_hub.protocol import CapabilitySnapshot, SessionClosed, SessionOpen, SessionPrepared, SessionStop, SessionView
from runbridge_hub.security import token_hash
from runbridge_hub.service import NodeService, ServiceError
from runbridge_hub.sessions import SessionService
from runbridge_hub.store import Store
from test_r1 import settings


TOKEN = "request-test-access-token"
KEY = ("grant_a", "node_a", "request_a")
ARGUMENTS = {"resource_id": "chromium", "lease_seconds": 30}


async def add_grant(*, store, grant_id="grant_a", token=TOKEN, expires_at=None):
    """写入仅供测试的许可摘要。"""
    await store.create_grant(values={"grant_id": grant_id, "node_id": "node_a", "token_hash": token_hash(token=token), "resource_ids": None, "created_at": datetime.now(UTC).isoformat(), "expires_at": expires_at})


@pytest.fixture
async def runtime(tmp_path):
    """模拟 Node 确认，保留真实授权、分配及清理逻辑。

    :yields: 请求服务及可调整的节点响应。
    """
    store = Store(path=tmp_path / "hub.sqlite3")
    await store.open()
    await store.register(node_id="node_a", name="请求恢复测试", token_digest="owner-test-digest")
    await add_grant(store=store)
    nodes = NodeService(store=store, settings=settings(tmp_path=tmp_path))
    sessions = SessionService(nodes=nodes)
    browsers = BrowserService(sessions=sessions, native_url="http://fixture")
    sessions.on_close = browsers.discard
    state = SimpleNamespace(store=store, nodes=nodes, sessions=sessions, browsers=browsers, cleanup="COMPLETE", prepare="ready")
    now = datetime.now(UTC)
    live = SimpleNamespace(node_id="node_a", generation=1, last_seen_at=now, heartbeat_count=0, capabilities_observed_at=now, capabilities=CapabilitySnapshot.model_validate({"backends": [{"name": "playwright", "runtime_version": "1.63.0", "coverage_status": "SUPPORTED"}], "resources": [{"resource_id": "chromium", "backend": "playwright", "kind": "MANAGED_CHROMIUM", "readiness": "READY", "occupancy": "FREE"}]}))
    nodes.connections["node_a"] = live

    async def send(*, message):
        if isinstance(message, SessionOpen):
            session = sessions.sessions[message.session_id]
            if state.prepare == "timeout":
                return
            if state.prepare == "send_error":
                raise OSError("fixture control transport lost")
            session.tunnel = SimpleNamespace(close=AsyncMock())
            await sessions.report(connection=live, message=SessionPrepared(connection_generation=1, session_id=message.session_id, runtime_version="1.63.0", error_code="PLAYWRIGHT_LAUNCH_FAILED" if state.prepare == "reported_error" else None))
            if state.prepare == "reported_error":
                await sessions.report(connection=live, message=SessionClosed(connection_generation=1, session_id=message.session_id, cleanup=state.cleanup))
        elif isinstance(message, SessionStop):
            await sessions.report(connection=live, message=SessionClosed(connection_generation=1, session_id=message.session_id, cleanup=state.cleanup))

    live.send = AsyncMock(side_effect=send)
    context = SimpleNamespace(on=lambda *args: None)
    page = SimpleNamespace(is_closed=lambda: False, on=lambda *args: None)
    context.new_page = AsyncMock(return_value=page)
    browser = SimpleNamespace(new_context=AsyncMock(return_value=context), close=AsyncMock())

    async def connect(**kwargs):
        session = next(item for item in sessions.sessions.values() if item.view.state == "READY")
        session.claimed = True
        session.view.state = "ACTIVE"
        await sessions._save(view=session.view)
        return browser

    state.connect = AsyncMock(side_effect=connect)
    browsers.playwright = SimpleNamespace(chromium=SimpleNamespace(connect=state.connect), stop=AsyncMock())
    state.open_arguments = {"node_id": "node_a", "token": TOKEN, "request_id": "request_a", **ARGUMENTS}
    try:
        yield state
    finally:
        await browsers.shutdown()
        await sessions.shutdown()
        await store.close()


async def lookup(*, runtime, token=TOKEN, request_id="request_a"):
    """通过生产查询路径核对请求身份。

    :returns: 请求及当前会话状态。
    """
    return await runtime.browsers.listing(node_id="node_a", token=token, request_id=request_id)


@pytest.mark.asyncio
@pytest.mark.parametrize("cleanup", ["UNKNOWN", "COMPLETE"])
async def test_connect_failure_retains_session_after_discard(runtime, cleanup):
    runtime.cleanup = cleanup
    runtime.connect.side_effect = Error("fixture credential must not escape")
    with pytest.raises(BrowserError, match="BROWSER_CONNECT_FAILED") as error:
        await runtime.browsers.open(**runtime.open_arguments)
    assert error.value.outcome == "OUTCOME_UNKNOWN"
    value = await lookup(runtime=runtime)
    assert value["request"]["state"] == "FAILED"
    assert len(value["sessions"]) == 1 and not runtime.browsers.entries
    session = value["sessions"][0]["session"]
    assert session["session_id"] == value["request"]["session_id"]
    assert (session["state"], session["cleanup"]) == ("FAILED", cleanup)
    assert value["sessions"][0]["request_id"] == "request_a"
    assert value["request"]["grant_id"] == "grant_a" and value["request"]["node_id"] == "node_a"
    assert not runtime.browsers.open_requests and not runtime.browsers.open_arguments
    with pytest.raises(BrowserError, match="BROWSER_CONNECT_FAILED"):
        await runtime.browsers.open(**runtime.open_arguments)
    assert runtime.connect.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("prepare", ["reported_error", "send_error", "timeout"])
async def test_prepare_failure_retains_atomic_allocation_identity(runtime, prepare, monkeypatch):
    runtime.prepare = prepare
    runtime.cleanup = "UNKNOWN"
    if prepare == "timeout":
        original = asyncio.wait_for
        async def short_wait(fut, timeout):
            return await original(fut=fut, timeout=0.01 if timeout == 30 else timeout)
        monkeypatch.setattr(asyncio, "wait_for", short_wait)
    with pytest.raises(BrowserError):
        await runtime.browsers.open(**runtime.open_arguments)
    value = await lookup(runtime=runtime)
    assert value["request"]["state"] == "FAILED"
    assert value["request"]["execution_outcome"] == "OUTCOME_UNKNOWN"
    assert value["sessions"][0]["session"]["session_id"] == value["request"]["session_id"]
    assert value["sessions"][0]["session"]["cleanup"] == "UNKNOWN"
    runtime.connect.assert_not_awaited()


@pytest.mark.asyncio
async def test_idempotent_open_survives_caller_cancel_and_returns_current_closed_state(runtime):
    ready, started = asyncio.Event(), asyncio.Event()
    connect = runtime.connect.side_effect
    async def wait_connect(**kwargs):
        started.set()
        await ready.wait()
        return await connect(**kwargs)
    runtime.connect.side_effect = wait_connect
    marker = REQUEST_TOKEN.set(SecretStr(TOKEN))
    first = asyncio.create_task(runtime.browsers.open(**runtime.open_arguments))
    try:
        await asyncio.wait_for(started.wait(), timeout=1)
        background = runtime.browsers.open_requests[KEY]
        assert background.get_context().get(REQUEST_TOKEN) is None
        reference = weakref.ref(background)
        first.cancel()
        with pytest.raises(asyncio.CancelledError):
            await first
        pending = await lookup(runtime=runtime)
        assert pending["request"]["state"] == "PENDING" and pending["request"]["session_id"]
        with pytest.raises(BrowserError, match="REQUEST_ARGUMENTS_MISMATCH"):
            await runtime.browsers.open(**{**runtime.open_arguments, "lease_seconds": 31})
        second = asyncio.create_task(runtime.browsers.open(**runtime.open_arguments))
        ready.set()
        result = await second
        assert result["session"]["state"] == "ACTIVE" and runtime.connect.await_count == 1
        del background
        await asyncio.sleep(0)
        gc.collect()
        assert reference() is None
        assert not runtime.browsers.open_requests and not runtime.browsers.open_arguments
        await runtime.sessions.release(session_id=result["session"]["session_id"], token=TOKEN)
        again = await runtime.browsers.open(**runtime.open_arguments)
        assert again["session"]["state"] == "CLOSED" and again["session"]["cleanup"] == "COMPLETE"
        assert runtime.connect.await_count == 1
        with pytest.raises(BrowserError, match="REQUEST_ARGUMENTS_MISMATCH"):
            await runtime.browsers.open(**{**runtime.open_arguments, "lease_seconds": 31})
    finally:
        REQUEST_TOKEN.reset(marker)


@pytest.mark.asyncio
async def test_worker_cancel_preserves_allocated_session_and_cleanup(runtime):
    started = asyncio.Event()
    async def interrupted(**kwargs):
        started.set()
        await asyncio.Event().wait()
    runtime.connect.side_effect = interrupted
    caller = asyncio.create_task(runtime.browsers.open(**runtime.open_arguments))
    await asyncio.wait_for(started.wait(), timeout=1)
    runtime.browsers.open_requests[KEY].cancel()
    with pytest.raises(BrowserError, match="REQUEST_CANCELLED"):
        await caller
    value = await lookup(runtime=runtime)
    assert value["request"]["state"] == "FAILED" and value["request"]["session_id"]
    assert value["sessions"][0]["session"]["cleanup"] == "COMPLETE"
    assert not runtime.browsers.open_requests


@pytest.mark.asyncio
async def test_cancel_during_request_admission_finishes_unallocated_record(runtime, monkeypatch):
    started = asyncio.Event()
    original = runtime.store.begin_mcp_request
    async def interrupted_admission(**kwargs):
        result = await original(**kwargs)
        started.set()
        await asyncio.Event().wait()
        return result
    monkeypatch.setattr(runtime.store, "begin_mcp_request", interrupted_admission)
    caller = asyncio.create_task(runtime.browsers.open(**runtime.open_arguments))
    await asyncio.wait_for(started.wait(), timeout=1)
    runtime.browsers.open_requests[KEY].cancel()
    with pytest.raises(BrowserError, match="REQUEST_CANCELLED") as failure:
        await caller
    assert failure.value.outcome == "NOT_STARTED"
    value = await lookup(runtime=runtime)
    assert value["request"]["state"] == "FAILED" and value["request"]["session_id"] is None
    assert not runtime.sessions.sessions and not runtime.browsers.open_requests


@pytest.mark.asyncio
async def test_unallocated_failure_is_distinct_from_missing_and_is_scoped(runtime):
    runtime.nodes.connections.clear()
    with pytest.raises(BrowserError, match="NODE_OFFLINE") as failure:
        await runtime.browsers.open(**runtime.open_arguments)
    value = await lookup(runtime=runtime)
    assert failure.value.outcome == "NOT_STARTED"
    assert value["request"]["state"] == "FAILED" and value["request"]["session_id"] is None
    assert value["request"]["execution_outcome"] == "NOT_STARTED" and value["sessions"] == []
    assert (await lookup(runtime=runtime, request_id="never_started"))["request"]["state"] == "NOT_FOUND"
    await add_grant(store=runtime.store, grant_id="grant_b", token="another-test-token")
    other = await lookup(runtime=runtime, token="another-test-token")
    assert other["request"]["state"] == "NOT_FOUND" and other["request"]["grant_id"] == "grant_b"
    with pytest.raises(ServiceError, match="NODE_OUTSIDE_GRANT"):
        await runtime.browsers.listing(node_id="another_node", token=TOKEN, request_id="request_a")


@pytest.mark.asyncio
async def test_failed_tasks_and_exceptions_are_released_without_secret_metadata(runtime):
    runtime.connect.side_effect = Error(TOKEN)
    with pytest.raises(BrowserError):
        await runtime.browsers.open(**runtime.open_arguments)
    assert not runtime.browsers.open_requests and not runtime.browsers.open_arguments
    row = await runtime.store.mcp_request(key=KEY)
    assert TOKEN not in str(row) and "traceback" not in str(row)


@pytest.mark.asyncio
async def test_unexpected_failure_preserves_identity_and_only_stable_error(runtime):
    runtime.connect.side_effect = RuntimeError(TOKEN)
    with pytest.raises(BrowserError, match="REQUEST_OUTCOME_UNKNOWN"):
        await runtime.browsers.open(**runtime.open_arguments)
    value = await lookup(runtime=runtime)
    assert value["request"]["state"] == "UNKNOWN" and value["request"]["session_id"]
    assert value["request"]["execution_outcome"] == "OUTCOME_UNKNOWN"
    assert TOKEN not in str(value) and not runtime.browsers.open_requests


@pytest.mark.asyncio
async def test_capacity_rejects_before_allocation_and_keeps_old_request(runtime, monkeypatch):
    monkeypatch.setattr("runbridge_hub.store.MCP_REQUEST_LIMIT", 1)
    runtime.nodes.connections.clear()
    for request_id, code in [("request_a", "NODE_OFFLINE"), ("request_b", "REQUEST_RECORD_LIMIT"), ("request_a", "NODE_OFFLINE")]:
        with pytest.raises(BrowserError, match=code):
            await runtime.browsers.open(**{**runtime.open_arguments, "request_id": request_id})
    assert not runtime.sessions.sessions and not runtime.browsers.open_requests
    assert (await lookup(runtime=runtime, request_id="request_b"))["request"]["state"] == "NOT_FOUND"


@pytest.mark.asyncio
async def test_running_limit_does_not_evict_or_duplicate_unknown_request(runtime, monkeypatch):
    monkeypatch.setattr("runbridge_hub.browser.PENDING_REQUEST_LIMIT", 1)
    ready, started = asyncio.Event(), asyncio.Event()
    connect = runtime.connect.side_effect
    async def waiting(**kwargs):
        started.set()
        await ready.wait()
        return await connect(**kwargs)
    runtime.connect.side_effect = waiting
    first = asyncio.create_task(runtime.browsers.open(**runtime.open_arguments))
    await asyncio.wait_for(started.wait(), timeout=1)
    with pytest.raises(BrowserError, match="REQUEST_CONCURRENCY_LIMIT"):
        await runtime.browsers.open(**{**runtime.open_arguments, "request_id": "request_b"})
    second = asyncio.create_task(runtime.browsers.open(**runtime.open_arguments))
    ready.set()
    results = await asyncio.gather(first, second)
    assert results[0] == results[1] and runtime.connect.await_count == 1


@pytest.mark.asyncio
async def test_expired_grant_records_reclaim_without_authorizing_old_replay(runtime):
    await add_grant(store=runtime.store, grant_id="expired", token="expired-test-token", expires_at=(datetime.now(UTC)-timedelta(seconds=1)).isoformat())
    expired_key = ("expired", "node_a", "old_request")
    await runtime.store.begin_mcp_request(key=expired_key, arguments=ARGUMENTS)
    await runtime.store.begin_mcp_request(key=KEY, arguments=ARGUMENTS)
    assert await runtime.store.mcp_request(key=expired_key) is None
    with pytest.raises(ServiceError, match="INVALID_ACCESS_TOKEN"):
        await runtime.browsers.open(**{**runtime.open_arguments, "token": "expired-test-token", "request_id": "old_request"})


@pytest.mark.asyncio
async def test_restart_preserves_pending_session_identity_without_replaying(runtime, monkeypatch):
    await runtime.store.begin_mcp_request(key=KEY, arguments=ARGUMENTS)
    now = datetime.now(UTC)
    view = SessionView(session_id="old_session", node_id="node_a", grant_id="grant_a", resource_id="chromium", connection_generation=1, backend="playwright", runtime_version="1.63.0", client_version="1.63.0", native_protocol="playwright", state="PREPARING", created_at=now, updated_at=now, expires_at=now+timedelta(seconds=30))
    await runtime.store.save_session(session_id=view.session_id, node_id="node_a", grant_id="grant_a", record=view.model_dump_json(), mcp_request_id="request_a")
    await runtime.store.close()
    await runtime.store.open()
    await runtime.sessions.start()
    monkeypatch.setattr("runbridge_hub.browser.async_playwright", lambda: SimpleNamespace(start=AsyncMock(return_value=runtime.browsers.playwright)))
    await runtime.browsers.start()
    value = await lookup(runtime=runtime)
    assert value["request"]["state"] == "UNKNOWN" and value["request"]["session_id"] == "old_session"
    assert value["sessions"][0]["session"]["state"] == "INTERRUPTED"
    assert value["sessions"][0]["session"]["cleanup"] == "UNKNOWN"
    with pytest.raises(BrowserError, match="REQUEST_OUTCOME_UNKNOWN"):
        await runtime.browsers.open(**runtime.open_arguments)
    runtime.connect.assert_not_awaited()
    assert not runtime.browsers.open_requests


@pytest.mark.asyncio
async def test_second_allocation_rolls_back_without_replacing_original_identity(runtime):
    await runtime.store.begin_mcp_request(key=KEY, arguments=ARGUMENTS)
    await runtime.store.save_session(session_id="first_session", node_id="node_a", grant_id="grant_a", record='{"session_id":"first_session"}', mcp_request_id="request_a")
    with pytest.raises(ValueError, match="不能重复分配"):
        await runtime.store.save_session(session_id="second_session", node_id="node_a", grant_id="grant_a", record='{"session_id":"second_session"}', mcp_request_id="request_a")
    assert await runtime.store.session(session_id="second_session") is None
    assert (await runtime.store.mcp_request(key=KEY))["session_id"] == "first_session"


@pytest.mark.asyncio
async def test_schema_two_migration_preserves_historical_metadata(runtime):
    await runtime.store.save_session(session_id="historical", node_id="node_a", grant_id="grant_a", record='{"session_id":"historical","state":"CLOSED","cleanup":"COMPLETE"}')
    await runtime.store.close()
    with sqlite3.connect(database=runtime.store.path) as database:
        database.executescript("DROP TABLE mcp_requests; PRAGMA user_version=2;")
    await runtime.store.open()
    assert (await runtime.store.session(session_id="historical"))["cleanup"] == "COMPLETE"
    assert await runtime.nodes.authorize_access(node_id="node_a", token=TOKEN)
    assert await runtime.store.mcp_request(key=KEY) is None
