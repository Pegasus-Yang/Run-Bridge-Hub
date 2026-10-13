"""MCP 持有的远程 Playwright 对象和受管理浏览器生命周期。"""

import asyncio
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import version
from uuid import uuid4

from playwright.async_api import Browser, BrowserContext, Error, Page, TimeoutError as PlaywrightTimeoutError, async_playwright

from runbridge_hub.protocol import SessionCreate
from runbridge_hub.service import ServiceError
from runbridge_hub.sessions import SessionService


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


class BrowserService:
    """将 MCP 工具绑定到现有会话服务，不自行启动 Hub 本机浏览器。"""

    def __init__(self, *, sessions: SessionService, native_url: str):
        self.sessions = sessions
        self.native_url = native_url.rstrip("/")
        self.entries: dict[str, BrowserSession] = {}
        self.playwright = None
        self.cleanup_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        """启动协议客户端驱动，不启动浏览器进程。"""
        self.playwright = await async_playwright().start()

    async def open(self, *, node_id: str, token: str, resource_id: str | None, lease_seconds: float) -> dict:
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
        created = await self.sessions.create(node_id=node_id, token=token, request=SessionCreate(resource_id=resource_id, client_version=version("playwright"), lease_seconds=lease_seconds))
        entry = BrowserSession(session_id=created.session_id, node_id=node_id, grant_id=created.grant_id)
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
                return {"session": current.model_dump(mode="json"), "page_id": page_id}
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
        pages = [{"page_id": page_id, "url": page.url} for page_id, page in entry.pages.items()] if entry is not None else []
        return {"session": view.model_dump(mode="json"), "pages": pages}

    async def listing(self, *, node_id: str, token: str) -> dict:
        """列出当前许可创建的活动 MCP 浏览器，不暴露其他许可。

        :returns: 当前活动会话。
        """
        grant = await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        ids = [entry.session_id for entry in self.entries.values() if entry.node_id == node_id and entry.grant_id == grant["grant_id"]]
        return {"sessions": [await self.status(session_id=session_id, token=token) for session_id in ids]}

    @asynccontextmanager
    async def page(self, *, session_id: str, page_id: str, token: str, timeout_ms: int, mutating: bool = False):
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
                    page = entry.pages.get(page_id)
                    if page is None or page.is_closed():
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
