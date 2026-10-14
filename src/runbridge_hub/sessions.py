"""独占资源、会话生命周期和原生连接归属。"""

import asyncio
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from runbridge_hub.protocol import SessionClosed, SessionConnect, SessionCreate, SessionOpen, SessionPrepared, SessionStop, SessionView
from runbridge_hub.service import Connection, NodeService, ServiceError


TERMINAL = {"CLOSED", "FAILED", "INTERRUPTED"}
NATIVE_MAX_BYTES = 16 * 1024 * 1024


def version_pair(*, value: str) -> tuple[int, int]:
    """比较官方远程协议要求的主、次版本。

    :returns: 主、次版本。
    """
    match = re.match(r"^(\d+)\.(\d+)(?:\.|$)", value)
    if match is None:
        raise ServiceError(status=409, code="BACKEND_VERSION_UNKNOWN")
    return int(match.group(1)), int(match.group(2))


async def close_websocket(*, websocket: WebSocket | None, reason: str) -> None:
    """关闭已经断开或正在运行的原生连接。

    :param websocket: 可选连接。
    :param reason: 无秘密的关闭原因。
    """
    if websocket is not None:
        try:
            await asyncio.wait_for(websocket.close(code=1000, reason=reason), timeout=3)
        except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
            pass


@dataclass
class Session:
    """只保留当前连接的路由与同步事件，不复活原生对象。"""

    view: SessionView
    connection: Connection
    prepared: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    cleaned: asyncio.Event = field(default_factory=asyncio.Event)
    tunnel: WebSocket | None = None
    caller: WebSocket | None = None
    caller_attached: asyncio.Event = field(default_factory=asyncio.Event)
    reader_released: asyncio.Event = field(default_factory=asyncio.Event)
    claimed: bool = False
    terminal_state: str = "CLOSED"


class SessionService:
    """和节点管理共用短临界区，串行确认资源及许可。"""

    def __init__(self, *, nodes: NodeService):
        self.nodes = nodes
        self.sessions: dict[str, Session] = {}
        self.maintenance_task = None
        self.on_close = None

    async def start(self) -> None:
        """把上次进程遗留的会话标为中断，启动租期检查。"""
        for record in await self.nodes.store.unfinished_sessions():
            view = SessionView.model_validate(record)
            view.state = "INTERRUPTED"
            view.cleanup = "UNKNOWN"
            view.native_path = None
            view.close_reason = "HUB_RESTARTED"
            view.updated_at = datetime.now(UTC)
            if view.execution_outcome != "NOT_STARTED":
                view.execution_outcome = "OUTCOME_UNKNOWN"
            await self._save(view=view)
        self.maintenance_task = asyncio.create_task(self._maintenance())

    async def _save(self, *, view: SessionView, mcp_request_id: str | None = None) -> None:
        """仅保存公开元数据。

        :param view: 会话视图。
        :param mcp_request_id: 仅首次分配时关联的 MCP 请求。
        """
        await self.nodes.store.save_session(session_id=view.session_id, node_id=view.node_id, grant_id=view.grant_id, record=view.model_dump_json(), mcp_request_id=mcp_request_id)

    async def create(self, *, node_id: str, token: str | None, request: SessionCreate, mcp_request_id: str | None = None) -> SessionView:
        """申请资源并等待节点确认，失败后禁止提前复用资源。

        :returns: 已就绪的会话。
        :param mcp_request_id: 内部 MCP 关联，不改变公开 SessionCreate 合同。
        """
        async with self.nodes.lock:
            grant = await self.nodes.authorize_access(node_id=node_id, token=token)
            if grant["resource_ids"] is not None and request.resource_id not in grant["resource_ids"]:
                raise ServiceError(status=403, code="RESOURCE_OUTSIDE_GRANT")
            live = self.nodes.connections.get(node_id)
            now = datetime.now(UTC)
            if live is None or live.capabilities is None or (now - live.last_seen_at).total_seconds() >= self.nodes.settings.heartbeat_timeout_seconds:
                raise ServiceError(status=409, code="NODE_OFFLINE")
            resource = next((item for item in live.capabilities.resources if item.resource_id == request.resource_id), None)
            if resource is None or (resource.backend, resource.kind) not in {("playwright", "MANAGED_CHROMIUM"), ("chrome-cdp", "BORROWED_CHROME_CDP")}:
                raise ServiceError(status=404, code="RESOURCE_NOT_FOUND")
            borrowed = resource.kind == "BORROWED_CHROME_CDP"
            if borrowed and resource.authorization_scope != "BROWSER_INSTANCE":
                raise ServiceError(status=409, code="RESOURCE_NOT_AUTHORIZED")
            if resource.readiness != "READY":
                raise ServiceError(status=409, code="RESOURCE_NOT_READY")
            key = (node_id, request.resource_id)
            if key in self.nodes.reservations or resource.occupancy != "FREE":
                raise ServiceError(status=409, code="RESOURCE_BUSY")
            backend = next((item for item in live.capabilities.backends if item.name == resource.backend), None)
            if backend is None or backend.coverage_status != "SUPPORTED" or backend.runtime_version is None:
                raise ServiceError(status=409, code="BACKEND_UNAVAILABLE")
            if borrowed and version_pair(value=request.client_version) < (1, 60):
                raise ServiceError(status=428, code="CDP_CLIENT_VERSION_UNSUPPORTED")
            if not borrowed and version_pair(value=request.client_version) != version_pair(value=backend.runtime_version):
                raise ServiceError(status=428, code="PLAYWRIGHT_VERSION_MISMATCH")
            expires = now + timedelta(seconds=request.lease_seconds)
            if grant["expires_at"] is not None:
                expires = min(expires, datetime.fromisoformat(grant["expires_at"]))
            view = SessionView(session_id=f"session_{uuid4().hex}", node_id=node_id, resource_id=request.resource_id, grant_id=grant["grant_id"], connection_generation=live.generation, backend=resource.backend, runtime_version=backend.runtime_version, client_version=request.client_version, native_protocol="cdp" if borrowed else "playwright", authorization_scope=resource.authorization_scope, state="PREPARING", created_at=now, updated_at=now, expires_at=expires)
            session = Session(view=view, connection=live)
            await self._save(view=view, mcp_request_id=mcp_request_id)
            self.sessions[view.session_id] = session
            self.nodes.reservations[key] = view.session_id
        try:
            await live.send(message=SessionOpen(connection_generation=live.generation, session_id=view.session_id, resource_id=request.resource_id))
            await asyncio.wait_for(session.prepared.wait(), timeout=30)
        except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
            await self.close(session=session, reason="PREPARE_TIMEOUT", terminal_state="FAILED")
            raise ServiceError(status=504, code="SESSION_PREPARE_FAILED") from None
        except asyncio.CancelledError:
            await self.close(session=session, reason="PREPARE_CANCELLED", terminal_state="FAILED")
            raise
        if session.view.state != "READY":
            raise ServiceError(status=409, code=session.view.error_code or session.view.close_reason or "SESSION_PREPARE_FAILED")
        return session.view.model_copy(deep=True)

    async def query(self, *, session_id: str, token: str | None) -> SessionView:
        """会话只能由创建它的许可查询，其他许可不能接管。

        :returns: 当前或持久会话状态。
        """
        record = await self.nodes.store.session(session_id=session_id)
        if record is None:
            raise ServiceError(status=404, code="SESSION_NOT_FOUND")
        view = SessionView.model_validate(record)
        grant = await self.nodes.authorize_access(node_id=view.node_id, token=token)
        if grant["grant_id"] != view.grant_id:
            raise ServiceError(status=403, code="SESSION_OUTSIDE_GRANT")
        return view

    async def report(self, *, connection: Connection, message: SessionPrepared | SessionClosed) -> None:
        """核验代次与会话归属后接受节点状态。

        :param connection: 已认证的当前控制连接。
        :param message: 节点准备或清理报告。
        """
        async with self.nodes.lock:
            session = self.sessions.get(message.session_id)
            if self.nodes.connections.get(connection.node_id) is not connection or message.connection_generation != connection.generation or session is None or session.connection is not connection:
                raise ServiceError(status=409, code="STALE_SESSION")
            view = session.view
            if isinstance(message, SessionPrepared):
                if view.state != "PREPARING":
                    return
                if message.error_code is not None:
                    view.state = "CLOSING"
                    session.terminal_state = "FAILED"
                    view.error_code = message.error_code
                elif session.tunnel is None or message.runtime_version != view.runtime_version:
                    raise ServiceError(status=409, code="INVALID_SESSION_PREPARATION")
                else:
                    view.state = "READY"
                    view.native_path = f"/v1/sessions/{view.session_id}/{view.native_protocol}"
                session.prepared.set()
            else:
                view.state = session.terminal_state
                view.cleanup = message.cleanup
                view.native_path = None
                view.close_reason = view.close_reason or "NATIVE_CLOSED"
                if message.error_code is not None:
                    view.error_code = message.error_code
                    if session.terminal_state != "FAILED":
                        view.state = "INTERRUPTED"
                    view.execution_outcome = "OUTCOME_UNKNOWN" if session.claimed else "NOT_STARTED"
                if message.cleanup == "COMPLETE":
                    self.nodes.reservations.pop((view.node_id, view.resource_id), None)
                session.prepared.set()
                session.finished.set()
                session.cleaned.set()
            view.updated_at = datetime.now(UTC)
            await self._save(view=view)
        if isinstance(message, SessionClosed):
            closing = [close_websocket(websocket=session.caller, reason=view.close_reason),
                       close_websocket(websocket=session.tunnel, reason=view.close_reason)]
            if self.on_close is not None:
                closing.insert(0, self.on_close(session_id=view.session_id, reason=view.close_reason))
            await asyncio.gather(*closing)

    async def attach_tunnel(self, *, node_id: str, session_id: str, generation: int, token: str | None, websocket: WebSocket) -> Session:
        """只允许本节点当前代次连接尚在准备的会话。

        :returns: 当前路由。
        """
        await self.nodes.authorize_owner(node_id=node_id, token=token)
        async with self.nodes.lock:
            session = self.sessions.get(session_id)
            live = self.nodes.connections.get(node_id)
            if session is None or session.view.node_id != node_id or session.connection is not live or session.view.connection_generation != generation or session.view.state != "PREPARING" or session.tunnel is not None:
                raise ServiceError(status=409, code="INVALID_SESSION_TUNNEL")
            await websocket.accept()
            session.tunnel = websocket
            return session

    async def attach_caller(self, *, session_id: str, token: str | None, websocket: WebSocket, native_protocol: str = "playwright") -> Session:
        """验证实际 SDK 版本，并且一个会话只接入一个调用连接。

        :returns: 获授权的原生路由。
        """
        async with self.nodes.lock:
            session = self.sessions.get(session_id)
            if session is None:
                raise ServiceError(status=404, code="SESSION_NOT_FOUND")
            grant = await self.nodes.authorize_access(node_id=session.view.node_id, token=token)
            if grant["grant_id"] != session.view.grant_id:
                raise ServiceError(status=403, code="SESSION_OUTSIDE_GRANT")
            if session.view.native_protocol != native_protocol:
                raise ServiceError(status=409, code="NATIVE_PROTOCOL_MISMATCH")
            if session.view.expires_at <= datetime.now(UTC):
                raise ServiceError(status=409, code="SESSION_EXPIRED")
            if session.view.state != "READY" or session.claimed:
                raise ServiceError(status=409, code="SESSION_NOT_CONNECTABLE")
            user_agent = websocket.headers.get("user-agent", "")
            match = re.search(r"Playwright/(\d+\.\d+\.\d+)", user_agent)
            expected = session.view.client_version if native_protocol == "cdp" else session.view.runtime_version
            if match is None or expected is None or version_pair(value=match.group(1)) != version_pair(value=expected):
                raise ServiceError(status=428, code="PLAYWRIGHT_VERSION_MISMATCH")
            if websocket.headers.get("x-playwright-browser", "chromium") != "chromium":
                raise ServiceError(status=400, code="BROWSER_TYPE_MISMATCH")
            if websocket.query_params:
                raise ServiceError(status=400, code="UNSUPPORTED_NATIVE_QUERY")
            headers = {key: value for key, value in websocket.headers.items() if key == "user-agent" or key.startswith("x-playwright-")}
            if sum(len(key) + len(value) for key, value in headers.items()) > 32_768:
                raise ServiceError(status=431, code="NATIVE_HEADERS_TOO_LARGE")
            session.claimed = True
            session.caller_attached.set()
            session.caller = websocket
            session.view.state = "ACTIVE"
            session.view.execution_outcome = "NOT_TRACKED"
            session.view.updated_at = datetime.now(UTC)
            await self._save(view=session.view)
        try:
            await asyncio.wait_for(session.reader_released.wait(), timeout=5)
            await session.connection.send(message=SessionConnect(connection_generation=session.view.connection_generation, session_id=session_id, headers=headers))
            await websocket.accept()
        except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
            await self.close(session=session, reason="NODE_DISCONNECTED", terminal_state="INTERRUPTED")
            raise ServiceError(status=409, code="NODE_OFFLINE") from None
        return session

    async def close(self, *, session: Session, reason: str, terminal_state: str = "CLOSED") -> None:
        """关闭原生路由并请求节点清理；未确认清理时保持占用。

        :param session: 当前会话。
        :param reason: 公开关闭原因。
        :param terminal_state: 清理后的技术状态。
        """
        async with self.nodes.lock:
            if session.view.state in TERMINAL or session.view.state == "CLOSING":
                return
            session.terminal_state = terminal_state
            session.view.state = "CLOSING"
            session.view.native_path = None
            session.view.close_reason = reason
            session.view.updated_at = datetime.now(UTC)
            if session.claimed and reason not in {"SESSION_RELEASED", "NATIVE_CLOSED"}:
                session.view.execution_outcome = "OUTCOME_UNKNOWN"
            await self._save(view=session.view)
            session.prepared.set()
            session.finished.set()
        closing = [close_websocket(websocket=session.caller, reason=reason),
                   close_websocket(websocket=session.tunnel, reason=reason)]
        if self.on_close is not None:
            closing.insert(0, self.on_close(session_id=session.view.session_id, reason=reason))
        # 画面清理不能延迟原生调用方收到中断，各连接分别限时退出。
        await asyncio.gather(*closing)
        try:
            await session.connection.send(message=SessionStop(connection_generation=session.view.connection_generation, session_id=session.view.session_id, reason=reason))
        except (WebSocketDisconnect, RuntimeError, OSError, TimeoutError):
            pass

    async def release(self, *, session_id: str, token: str | None) -> SessionView:
        """释放接口幂等，等待清理报告后返回真实清理状态。

        :returns: 终止或尚在清理的状态。
        """
        view = await self.query(session_id=session_id, token=token)
        session = self.sessions.get(session_id)
        if session is not None and view.state not in TERMINAL:
            await self.close(session=session, reason="SESSION_RELEASED")
            try:
                await asyncio.wait_for(session.cleaned.wait(), timeout=10)
            except TimeoutError:
                pass
            return session.view.model_copy(deep=True)
        return view

    async def revoke(self, *, node_id: str, grant_id: str, token: str | None) -> None:
        """撤销许可与资源申请共用临界区，再关闭已有执行连接。

        :param node_id: 节点 ID。
        :param grant_id: 许可 ID。
        :param token: 节点身份凭据。
        """
        await self.nodes.authorize_owner(node_id=node_id, token=token)
        async with self.nodes.lock:
            if not await self.nodes.store.revoke(node_id=node_id, grant_id=grant_id, revoked_at=datetime.now(UTC).isoformat()):
                raise ServiceError(status=404, code="GRANT_NOT_FOUND")
            affected = [item for item in self.sessions.values() if item.view.node_id == node_id and item.view.grant_id == grant_id]
        for session in affected:
            await self.close(session=session, reason="GRANT_REVOKED")

    async def interrupt_node(self, *, node_id: str, generation: int) -> None:
        """连接代次失效时不把旧资源清理假定为成功。

        :param node_id: 失联节点。
        :param generation: 失效代次。
        """
        affected = [item for item in self.sessions.values() if item.view.node_id == node_id and item.view.connection_generation == generation and item.view.state not in TERMINAL]
        for session in affected:
            await self.close(session=session, reason="NODE_DISCONNECTED", terminal_state="INTERRUPTED")
            async with self.nodes.lock:
                session.view.state = "INTERRUPTED"
                session.view.cleanup = "UNKNOWN"
                session.view.updated_at = datetime.now(UTC)
                self.nodes.reservations.pop((node_id, session.view.resource_id), None)
                session.cleaned.set()
                await self._save(view=session.view)

    async def _maintenance(self) -> None:
        """检查租期与清理超时，高频协议帧不访问数据库。"""
        while True:
            await asyncio.sleep(0.25)
            now = datetime.now(UTC)
            for session in list(self.sessions.values()):
                if session.view.state in TERMINAL:
                    if session.view.cleanup == "COMPLETE" or session.view.state == "INTERRUPTED" or self.nodes.connections.get(session.view.node_id) is not session.connection:
                        self.sessions.pop(session.view.session_id, None)
                    continue
                if session.view.state == "CLOSING":
                    if (now - session.view.updated_at).total_seconds() >= 10:
                        async with self.nodes.lock:
                            if session.view.state == "CLOSING":
                                session.view.state = session.terminal_state
                                session.view.cleanup = "UNKNOWN"
                                session.view.updated_at = now
                                session.cleaned.set()
                                await self._save(view=session.view)
                elif session.view.expires_at <= now:
                    await self.close(session=session, reason="SESSION_EXPIRED")

    async def shutdown(self) -> None:
        """停止租期任务，再中断本进程拥有的路由。"""
        if self.maintenance_task is not None:
            self.maintenance_task.cancel()
            await asyncio.gather(self.maintenance_task, return_exceptions=True)
        for node_id, generation in {(item.view.node_id, item.view.connection_generation) for item in self.sessions.values()}:
            await self.interrupt_node(node_id=node_id, generation=generation)
