"""登记、访问许可和进程内在线状态。"""

import asyncio
import json
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import WebSocket, WebSocketDisconnect
from anyio import BrokenResourceError, ClosedResourceError

from runbridge_hub.protocol import Acknowledgement, CapabilityReport, CapabilitySnapshot, Heartbeat, NodeView, Registration, RegistrationResult
from runbridge_hub.security import matches, token_hash
from runbridge_hub.settings import HubSettings
from runbridge_hub.store import Store


class ServiceError(Exception):
    """只携带公开错误码，不包含凭据或请求原文。"""

    def __init__(self, *, status: int, code: str):
        self.status = status
        self.code = code
        super().__init__(code)


@dataclass
class Connection:
    """一条控制连接拥有自己的代次和最新观察。"""

    node_id: str
    generation: int
    websocket: WebSocket
    last_seen_at: datetime
    heartbeat_count: int = 0
    capabilities: CapabilitySnapshot | None = None
    capabilities_observed_at: datetime | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    control_rtt: Callable[[], dict] | None = None

    async def send(self, *, message) -> None:
        """串行发送控制消息，避免确认和执行命令交错。

        :param message: 已校验控制模型。
        """
        async with self.send_lock:
            await asyncio.wait_for(self.websocket.send_json(message.model_dump(mode="json")), timeout=5)


class NodeService:
    """协调持久记录和当前进程中的活连接。"""

    def __init__(self, *, store: Store, settings: HubSettings):
        self.store = store
        self.settings = settings
        self.connections: dict[str, Connection] = {}
        self.lock = asyncio.Lock()
        self.reservations: dict[tuple[str, str], str] = {}
        self.on_disconnect = None
        self.leases = None
        self.enrollment_digest = token_hash(token=settings.enrollment_token.get_secret_value())

    async def register(self, *, request: Registration, token: str | None) -> RegistrationResult:
        """验证登记许可并保持节点身份不可覆盖。

        :param request: 节点身份。
        :param token: 部署方登记凭据。
        :returns: 无秘密的登记结果。
        """
        if token is None or not matches(token=token, expected_hash=self.enrollment_digest):
            raise ServiceError(status=401, code="INVALID_ENROLLMENT_TOKEN")
        node, created = await self.store.register(node_id=request.node_id, name=request.name, token_digest=token_hash(token=request.node_token.get_secret_value()))
        if not matches(token=request.node_token.get_secret_value(), expected_hash=node["token_hash"]):
            raise ServiceError(status=409, code="NODE_IDENTITY_CONFLICT")
        return RegistrationResult(node_id=request.node_id, created=created)

    async def authorize_device(self, *, node_id: str, token: str | None) -> dict:
        """验证节点身份，仅用于控制、执行连接及画面上传。

        :param node_id: 节点 ID。
        :param token: 节点身份凭据。
        :returns: 登记记录。
        """
        node = await self.store.node(node_id=node_id)
        if node is None or token is None or not matches(token=token, expected_hash=node["token_hash"]):
            raise ServiceError(status=401, code="INVALID_NODE_TOKEN")
        return node

    async def resolve_access(self, *, token: str | None) -> dict:
        """委托租约服务逐请求验证调用能力。"""
        return await self.leases.resolve(token=token)

    async def authorize_access(self, *, node_id: str, token: str | None) -> dict:
        """验证调用凭据及节点范围，执行前需在短临界区中复核。

        :returns: 有效许可记录。
        """
        grant = await self.resolve_access(token=token)
        if grant["node_id"] != node_id:
            raise ServiceError(status=403, code="NODE_OUTSIDE_GRANT")
        return grant

    async def query(self, *, node_id: str, token: str | None) -> NodeView:
        """验证调用许可并返回带新鲜度的资源视图。

        :param node_id: 节点 ID。
        :param token: 对接凭据。
        :returns: 当前连接与能力信息。
        """
        now = datetime.now(UTC)
        node = await self.store.node(node_id=node_id)
        async with self.lock:
            await self.authorize_access(node_id=node_id, token=token)
            view = self._node_view(node=node, now=now)
            return view

    async def overview(self) -> list[NodeView]:
        """读取全局只读视图，调用方负责总览鉴权。

        :returns: 与调用接口采用相同占用及连接判断的节点列表。
        """
        records = await self.store.nodes()
        async with self.lock:
            now = datetime.now(UTC)
            return [self._node_view(node=node, now=now) for node in records]

    def _node_view(self, *, node: dict, now: datetime) -> NodeView:
        """在持有状态锁时投影连接、快照与 Hub 的资源预留。

        :param node: 持久节点记录。
        :param now: 本次查询时间。
        :returns: 不含身份秘密的节点视图。
        """
        node_id = node["node_id"]
        live = self.connections.get(node_id)
        capabilities = live.capabilities.model_copy(deep=True) if live is not None and live.capabilities is not None else (CapabilitySnapshot.model_validate_json(node["capabilities"]) if node["capabilities"] is not None else None)
        observed = live.capabilities_observed_at if live is not None and live.capabilities_observed_at is not None else (datetime.fromisoformat(node["capabilities_observed_at"]) if node["capabilities_observed_at"] is not None else None)
        online = live is not None and (now - live.last_seen_at).total_seconds() < self.settings.heartbeat_timeout_seconds
        status = ("ONLINE" if live.capabilities is not None else "PREPARING") if online else "OFFLINE"
        if capabilities is not None:
            for resource in capabilities.resources:
                if (node_id, resource.resource_id) in self.reservations:
                    resource.occupancy = "BUSY"
        return NodeView(
            node_id=node_id, name=node["name"], connection_status=status,
            connection_generation=live.generation if live is not None else node["generation"],
            heartbeat_count=live.heartbeat_count if live is not None else 0,
            last_seen_at=live.last_seen_at if live is not None else node["last_seen_at"],
            capabilities_observed_at=observed,
            observation_age_ms=max(0, int((now - observed).total_seconds() * 1000)) if observed is not None else None,
            capabilities_stale=status != "ONLINE", capabilities=capabilities,
        )

    async def attach(self, *, node_id: str, websocket: WebSocket) -> Connection:
        """替换旧连接，新代次不被迟到的旧连接清理覆盖。

        :param node_id: 已认证节点。
        :param websocket: 新控制连接。
        :returns: 新连接状态。
        """
        async with self.lock:
            now = datetime.now(UTC)
            generation = await self.store.next_generation(node_id=node_id, observed_at=now.isoformat())
            current = Connection(
                node_id=node_id, generation=generation, websocket=websocket, last_seen_at=now,
                control_rtt=websocket.scope.get("extensions", {}).get("runbridge.control_rtt"),
            )
            previous = self.connections.get(node_id)
            self.connections[node_id] = current
        if previous is not None:
            if self.on_disconnect is not None:
                await self.on_disconnect(node_id=node_id, generation=previous.generation)
            try:
                await previous.websocket.close(code=4001, reason="connection_replaced")
            except (WebSocketDisconnect, RuntimeError, BrokenResourceError, ClosedResourceError):
                pass
        return current

    async def receive(self, *, connection: Connection, message: Heartbeat | CapabilityReport) -> Acknowledgement:
        """处理当前代次的能力更新或心跳。

        :param connection: 当前连接对象。
        :param message: 已校验控制消息。
        :returns: 服务器观察确认。
        """
        async with self.lock:
            if self.connections.get(connection.node_id) is not connection or message.connection_generation != connection.generation:
                raise ServiceError(status=409, code="STALE_CONNECTION")
            if isinstance(message, Heartbeat) and connection.capabilities is None:
                raise ServiceError(status=409, code="CAPABILITIES_REQUIRED")
            now = datetime.now(UTC)
            if isinstance(message, CapabilityReport):
                previous = connection.capabilities
                if previous is None:
                    stored = await self.store.node(node_id=connection.node_id)
                    previous = CapabilitySnapshot.model_validate_json(stored["capabilities"]) if stored["capabilities"] else None
                bound = {item.resource_id: item.tool for item in previous.resources} if previous else {}
                if any(item.resource_id in bound and bound[item.resource_id] != item.tool for item in message.capabilities.resources):
                    raise ServiceError(status=409, code="RESOURCE_TOOL_REBIND_FORBIDDEN")
                await self.store.snapshot(node_id=connection.node_id, generation=connection.generation, capabilities=message.capabilities.model_dump_json(), observed_at=now.isoformat())
                connection.capabilities = message.capabilities
                connection.capabilities_observed_at = now
                for resource in message.capabilities.resources:
                    key = (connection.node_id, resource.resource_id)
                    session_id = self.reservations.get(key)
                    if session_id is not None and resource.readiness == "READY" and resource.occupancy == "FREE":
                        record = await self.store.session(session_id=session_id)
                        if record is not None and record["connection_generation"] != connection.generation:
                            self.reservations.pop(key, None)
                kind = "capabilities_ack"
            else:
                connection.heartbeat_count += 1
                kind = "heartbeat_ack"
            connection.last_seen_at = now
            return Acknowledgement(type=kind, connection_generation=connection.generation, observed_at=now, heartbeat_count=connection.heartbeat_count)

    async def detach(self, *, connection: Connection) -> None:
        """仅移除仍然属于此连接的在线状态。

        :param connection: 断开的连接。
        """
        detached = False
        async with self.lock:
            if self.connections.get(connection.node_id) is connection:
                detached = True
                del self.connections[connection.node_id]
                await self.store.disconnected(node_id=connection.node_id, generation=connection.generation, last_seen_at=connection.last_seen_at.isoformat())

        if detached and self.on_disconnect is not None:
            await self.on_disconnect(node_id=connection.node_id, generation=connection.generation)

    async def close(self) -> None:
        """关闭服务进程仍持有的控制连接。"""
        for connection in list(self.connections.values()):
            try:
                await connection.websocket.close(code=1012, reason="service_restart")
            except (WebSocketDisconnect, RuntimeError, BrokenResourceError, ClosedResourceError):
                pass
            await self.detach(connection=connection)
