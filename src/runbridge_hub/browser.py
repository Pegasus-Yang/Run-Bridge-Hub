"""MCP 持有的远程 Playwright 对象和受管理浏览器生命周期。"""

import asyncio
import json
from contextlib import asynccontextmanager, suppress
from contextvars import Context
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, Error, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from runbridge_hub.protocol import SessionCreate
from runbridge_hub.managed_visual import ManagedCapture
from runbridge_hub.service import ServiceError
from runbridge_hub.sessions import SessionService


PENDING_REQUEST_LIMIT = 64


class BrowserError(ServiceError):
    """工具失败只暴露稳定错误码，写操作失败保留结果未知语义。"""

    def __init__(self, *, code: str, outcome: str = "NOT_STARTED"):
        super().__init__(status=409, code=code)
        self.outcome = outcome


@dataclass
class BrowserSession:
    """对象句柄仅存于 Hub 内存，不持久保存访问凭据。"""

    session_id: str
    node_id: str
    grant_id: str
    browser: Browser | None = None
    context: BrowserContext | None = None
    pages: dict[str, Page] = field(default_factory=dict)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    operations: set[asyncio.Task] = field(default_factory=set)
    closed: bool = False
    visual: ManagedCapture | None = None
    dialog_policy: dict = field(default_factory=dict)
    last_dialog: dict = field(default_factory=dict)
    request_id: str | None = None


class BrowserService:
    """将 MCP 工具绑定到现有会话服务，不自行启动 Hub 本机浏览器。"""

    def __init__(self, *, sessions: SessionService, native_url: str, visual=None):
        self.sessions = sessions
        self.native_url = native_url.rstrip("/")
        self.entries: dict[str, BrowserSession] = {}
        self.playwright = None
        self.cleanup_tasks: set[asyncio.Task] = set()
        self.visual = visual
        self.open_requests: dict[tuple[str, str, str], asyncio.Task] = {}
        self.open_arguments: dict[tuple[str, str, str], dict] = {}
        self.request_lock = asyncio.Lock()

    async def start(self) -> None:
        """启动协议客户端驱动，不启动浏览器进程。"""
        await self.sessions.nodes.store.interrupt_mcp_requests()
        self.playwright = await async_playwright().start()

    async def open(self, *, node_id: str, token: str, resource_id: str | None, lease_seconds: float, request_id: str | None = None) -> dict:
        """有请求标识时只创建一次，响应丢失不重复申请资源。

        :returns: 同一请求的原始创建结果。
        """
        if request_id is None:
            return await self._open(node_id=node_id, token=token, resource_id=resource_id, lease_seconds=lease_seconds)
        grant = await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        key = (grant["grant_id"], node_id, request_id)
        arguments = {"resource_id": resource_id, "lease_seconds": lease_seconds}
        async with self.request_lock:
            record = await self.sessions.nodes.store.mcp_request(key=key)
            task = self.open_requests.get(key)
            if record is not None and json.loads(record["arguments"]) != arguments:
                raise BrowserError(code="REQUEST_ARGUMENTS_MISMATCH")
            if task is not None and self.open_arguments[key] != arguments:
                raise BrowserError(code="REQUEST_ARGUMENTS_MISMATCH")
            if task is None and record is None:
                if len(self.open_requests) >= PENDING_REQUEST_LIMIT:
                    raise BrowserError(code="REQUEST_CONCURRENCY_LIMIT")
                # 独立上下文不继承 MCP 的 Bearer、请求对象及传输通道。
                task = asyncio.create_task(self._run_open(key=key, token=token, arguments=arguments), context=Context())
                task.add_done_callback(lambda done: done.exception() if not done.cancelled() else None, context=Context())
                self.open_requests[key] = task
                self.open_arguments[key] = arguments
        if task is not None:
            record = await asyncio.shield(task)
        # 等待期间可能撤销或到期，旧结果不能绕过本次授权。
        await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        if record is None or record["state"] in {"PENDING", "UNKNOWN"}:
            raise BrowserError(code="REQUEST_OUTCOME_UNKNOWN", outcome="OUTCOME_UNKNOWN")
        if record["state"] == "FAILED":
            raise BrowserError(code=record["error_code"], outcome=record["execution_outcome"])
        current = await self.sessions.query(session_id=record["session_id"], token=token)
        return {"session": current.model_dump(mode="json"), "page_id": record["page_id"], "request_id": request_id}

    async def _run_open(self, *, key: tuple[str, str, str], token: str, arguments: dict) -> dict | None:
        """创建任务只保留至完成，失败也保存分配身份和稳定错误码。

        :returns: 无凭据终态记录。
        """
        store = self.sessions.nodes.store
        try:
            try:
                record, fresh = await store.begin_mcp_request(key=key, arguments=arguments)
                if record is None:
                    return {"state": "FAILED", "error_code": "REQUEST_RECORD_LIMIT", "execution_outcome": "NOT_STARTED"}
                if not fresh:
                    return record
                result = await self._open(node_id=key[1], token=token, request_id=key[2], **arguments)
            except asyncio.CancelledError:
                await store.finish_mcp_request(key=key, state="FAILED", error_code="REQUEST_CANCELLED")
            except ServiceError as error:
                await store.finish_mcp_request(key=key, state="FAILED", error_code=error.code)
            except Exception:
                await store.finish_mcp_request(key=key, state="UNKNOWN", error_code="REQUEST_OUTCOME_UNKNOWN")
            else:
                await store.finish_mcp_request(key=key, state="SUCCEEDED", page_id=result["page_id"])
            return await store.mcp_request(key=key)
        finally:
            self.open_requests.pop(key, None)
            self.open_arguments.pop(key, None)

    async def _open(self, *, node_id: str, token: str, resource_id: str | None, lease_seconds: float, request_id: str | None = None) -> dict:
        """申请新受管理实例并连接 Hub 原生入口。

        :returns: 会话状态和首个页面句柄。
        """
        grant = await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        view = await self.sessions.nodes.query(node_id=node_id, token=token)
        if view.connection_status != "ONLINE":
            raise BrowserError(code="NODE_OFFLINE")
        resources = view.capabilities.resources if view.capabilities is not None else []
        managed = [item for item in resources if (item.backend, item.kind) == ("playwright", "MANAGED_CHROMIUM")]
        if resource_id is None:
            if len(managed) != 1:
                raise BrowserError(code="MANAGED_RESOURCE_REQUIRED")
            resource_id = managed[0].resource_id
        if grant["resource_ids"] is not None and resource_id not in grant["resource_ids"]:
            raise ServiceError(status=403, code="RESOURCE_OUTSIDE_GRANT")
        if resource_id not in {item.resource_id for item in managed}:
            raise BrowserError(code="MANAGED_RESOURCE_REQUIRED")
        created = await self.sessions.create(node_id=node_id, token=token, request=SessionCreate(resource_id=resource_id, client_version=version("playwright"), lease_seconds=lease_seconds), mcp_request_id=request_id)
        entry = BrowserSession(session_id=created.session_id, node_id=node_id, grant_id=created.grant_id, request_id=request_id)
        self.entries[created.session_id] = entry
        try:
            endpoint = self.native_url.replace("https://", "wss://", 1).replace("http://", "ws://", 1) + created.native_path
            async with asyncio.timeout(20):
                entry.browser = await self.playwright.chromium.connect(endpoint=endpoint, headers={"Authorization": f"Bearer {token}"}, timeout=15000)
                # 租期或撤销可能发生在连接建立期间，连接完成不能复活已清理的条目。
                if entry.closed:
                    raise BrowserError(code="SESSION_NOT_ACTIVE")
                entry.context = await entry.browser.new_context(viewport={"width": 1280, "height": 720}, locale="zh-CN")
                entry.context.on("page", lambda page: self._remember_page(entry=entry, page=page))
                page = await entry.context.new_page()
                page_id = self._remember_page(entry=entry, page=page)
                current = await self.sessions.query(session_id=created.session_id, token=token)
                if current.state != "ACTIVE" or current.expires_at <= datetime.now(UTC) or entry.closed:
                    raise BrowserError(code="SESSION_NOT_ACTIVE")
                if self.visual is not None and getattr(view.capabilities, "host", {}).get("managed_visual") == "cdp-png":
                    entry.visual = ManagedCapture(visual=self.visual, session=self.sessions.sessions[created.session_id], entry=entry)
                    await entry.visual.select(target_id=page_id)
                return {"session": current.model_dump(mode="json"), "page_id": page_id, "request_id": request_id}
        except BaseException as error:
            task = asyncio.create_task(self._failed_open(entry=entry))
            self.cleanup_tasks.add(task)
            task.add_done_callback(self.cleanup_tasks.discard)
            await asyncio.shield(task)
            if isinstance(error, (asyncio.CancelledError, ServiceError)):
                raise
            if isinstance(error, (Error, TimeoutError)):
                raise BrowserError(code="BROWSER_CONNECT_FAILED") from None
            raise

    def _remember_page(self, *, entry: BrowserSession, page: Page) -> str:
        """分配会话内不透明句柄。

        :returns: 页面 ID。
        """
        for page_id, existing in entry.pages.items():
            if existing is page:
                return page_id
        page_id = f"page_{uuid4().hex}"
        if not entry.closed:
            entry.pages[page_id] = page
            page.on("close", lambda: entry.pages.pop(page_id, None))
            async def handle_dialog(dialog):
                entry.last_dialog[page_id] = {"type": dialog.type, "message": dialog.message}
                policy = entry.dialog_policy.pop(page_id, {})
                with suppress(Error):
                    if policy.get("accept"):
                        await dialog.accept(prompt_text=policy.get("prompt_text") or "")
                    else:
                        await dialog.dismiss()
            page.on("dialog", handle_dialog)
        return page_id

    async def _failed_open(self, *, entry: BrowserSession) -> None:
        """连接失败或调用取消时仍请求 Node 清理，再释放迟到的 SDK 连接。"""
        session = self.sessions.sessions.get(entry.session_id)
        if session is not None:
            await self.sessions.close(session=session, reason="MCP_CONNECT_FAILED", terminal_state="FAILED")
            with suppress(TimeoutError):
                await asyncio.wait_for(session.cleaned.wait(), timeout=10)
        await self._disconnect(entry=entry)

    async def _disconnect(self, *, entry: BrowserSession) -> None:
        """释放 SDK 连接；这不是 Node 清理成功的证据。"""
        if entry.browser is not None:
            with suppress(Error, TimeoutError):
                await asyncio.wait_for(entry.browser.close(), timeout=2)

    async def discard(self, *, session_id: str, reason: str) -> None:
        """生命周期回调不争用工具锁，停止和撤销可打断长操作。"""
        entry = self.entries.pop(session_id, None)
        if entry is None:
            return
        entry.closed = True
        if entry.visual:
            await entry.visual.close()
        for task in list(entry.operations):
            if task is not asyncio.current_task():
                task.cancel()
        entry.pages.clear()
        # 原生路由正由 SessionService 关闭；此时发送 SDK close 会与隧道关闭竞争。
        # 先让 Node 完成真实清理，再回收 SDK 句柄，不阻塞停止命令或工具锁。
        task = asyncio.create_task(self._disconnect_after_cleanup(entry=entry))
        self.cleanup_tasks.add(task)
        task.add_done_callback(self.cleanup_tasks.discard)

    async def _disconnect_after_cleanup(self, *, entry: BrowserSession) -> None:
        """等待节点报告或清理超时后释放客户端对象。"""
        session = self.sessions.sessions.get(entry.session_id)
        if session is not None:
            with suppress(TimeoutError):
                await asyncio.wait_for(session.cleaned.wait(), timeout=10)
        await self._disconnect(entry=entry)

    async def status(self, *, session_id: str, token: str) -> dict:
        """查询技术状态，页面列表只包含本 MCP 服务持有的句柄。

        :returns: 会话视图及页面目录。
        """
        view = await self.sessions.query(session_id=session_id, token=token)
        entry = self.entries.get(session_id)
        pages = [{"page_id": page_id, "url": page.url} for page_id, page in list(entry.pages.items())] if entry is not None else []
        return {"session": view.model_dump(mode="json"), "pages": pages, "request_id": entry.request_id if entry else None, "visual": self.visual.describe(view=view).model_dump(mode="json") if self.visual else None}

    async def tabs(self, *, session_id: str, token: str, action: str, page_id: str | None, timeout_ms: int) -> dict:
        """只修改本 MCP 服务持有的页面对象。

        :returns: 页面目录及明确选择的页面。
        """
        if action == "list":
            return await self.status(session_id=session_id, token=token)
        if action == "select" and page_id is None:
            raise BrowserError(code="PAGE_ID_REQUIRED")
        await self.sessions.query(session_id=session_id, token=token)
        entry = self.entries.get(session_id)
        if entry is None or entry.closed:
            raise BrowserError(code="SESSION_NOT_ACTIVE")
        if action == "close" and page_id is None:
            raise BrowserError(code="PAGE_ID_REQUIRED")
        async with self.page(session_id=session_id, page_id=None if action == "new" else page_id, token=token, timeout_ms=timeout_ms, mutating=True) as target:
            if action == "new":
                page_id = self._remember_page(entry=entry, page=await target.new_page())
            elif action == "close":
                await target.close()
                page_id = None
            if entry.visual and page_id is not None:
                await entry.visual.select(target_id=page_id)
        return {**(await self.status(session_id=session_id, token=token)), "page_id": page_id}

    async def set_dialog(self, *, session_id: str, page_id: str, token: str, accept: bool, prompt_text: str | None) -> None:
        """在触发弹窗前保存一次性策略，避免等待工具锁死。"""
        await self.sessions.query(session_id=session_id, token=token)
        entry = self.entries.get(session_id)
        if entry is None or entry.closed or page_id not in entry.pages:
            raise BrowserError(code="PAGE_NOT_FOUND")
        entry.dialog_policy[page_id] = {"accept": accept, "prompt_text": prompt_text}

    async def listing(self, *, node_id: str, token: str, request_id: str | None = None) -> dict:
        """列出当前许可创建的活动 MCP 浏览器，不暴露其他许可。

        :returns: 当前活动会话。
        """
        grant = await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        ids = [entry.session_id for entry in self.entries.values() if entry.node_id == node_id and entry.grant_id == grant["grant_id"]]
        request = None
        if request_id is not None:
            key = (grant["grant_id"], node_id, request_id)
            record = await self.sessions.nodes.store.mcp_request(key=key)
            ids = [record["session_id"]] if record is not None and record["session_id"] else []
            request = {"request_id": request_id, "node_id": node_id, "grant_id": grant["grant_id"], "state": record["state"] if record else ("PENDING" if key in self.open_requests else "NOT_FOUND"), "session_id": record["session_id"] if record else None, "error_code": record["error_code"] if record else None, "execution_outcome": record["execution_outcome"] if record else None}
        values = [await self.status(session_id=session_id, token=token) for session_id in ids]
        if request_id is not None:
            for value in values:
                value["request_id"] = request_id
        return {"sessions": values, **({"request": request} if request is not None else {})}

    @asynccontextmanager
    async def page(self, *, session_id: str, page_id: str | None, token: str, timeout_ms: int, mutating: bool = False):
        """串行操作同一浏览器，排队后再次校验许可与租期。

        :yields: 此会话拥有的页面。
        """
        await self.sessions.query(session_id=session_id, token=token)
        entry = self.entries.get(session_id)
        if entry is None or entry.closed:
            raise BrowserError(code="SESSION_NOT_ACTIVE")
        task = asyncio.current_task()
        entry.operations.add(task)
        outcome = "NOT_STARTED"
        try:
            async with asyncio.timeout(timeout_ms / 1000):
                async with entry.lock:
                    view = await self.sessions.query(session_id=session_id, token=token)
                    if entry.closed or view.state != "ACTIVE" or view.expires_at <= datetime.now(UTC):
                        raise BrowserError(code="SESSION_NOT_ACTIVE")
                    page = entry.context if page_id is None else entry.pages.get(page_id)
                    if page is None or (page_id is not None and page.is_closed()):
                        raise BrowserError(code="PAGE_NOT_FOUND")
                    outcome = "OUTCOME_UNKNOWN" if mutating else "NOT_TRACKED"
                    yield page
        except (TimeoutError, PlaywrightTimeoutError, AssertionError):
            raise BrowserError(code="OPERATION_TIMEOUT", outcome=outcome) from None
        except Error:
            raise BrowserError(code="OPERATION_INTERRUPTED" if entry.closed else "OPERATION_FAILED", outcome=outcome) from None
        except asyncio.CancelledError:
            if entry.closed:
                raise BrowserError(code="OPERATION_INTERRUPTED", outcome=outcome) from None
            raise
        finally:
            entry.operations.discard(task)

    async def shutdown(self) -> None:
        """通过会话服务请求清理所有自建实例，最后停止 SDK 驱动。"""
        pending = [task for task in self.open_requests.values() if not task.done()]
        for task in pending:
            task.cancel()
        if pending:
            await asyncio.gather(*pending, return_exceptions=True)
        for entry in list(self.entries.values()):
            session = self.sessions.sessions.get(entry.session_id)
            if session is not None:
                await self.sessions.close(session=session, reason="SESSION_RELEASED")
                with suppress(TimeoutError):
                    await asyncio.wait_for(session.cleaned.wait(), timeout=10)
        if self.cleanup_tasks:
            await asyncio.gather(*self.cleanup_tasks)
        if self.playwright is not None:
            await self.playwright.stop()
