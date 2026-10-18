"""会话画面的内存路由、最新帧和有界订阅分发。"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from fastapi import WebSocket

from runbridge_hub.protocol import NodeView, SessionView
from runbridge_hub.service import ServiceError
from runbridge_hub.sessions import Session, SessionService, TERMINAL, close_websocket
from runbridge_hub.visual_protocol import VISUAL_PROTOCOL, NodeVisualView, VisualFrame, VisualSelection, VisualSourceState, VisualStreamView, VisualTarget, VisualView


STALE_SECONDS = 5
SELECTION_SECONDS = 10


@dataclass
class VisualChannel:
    """同一会话只保留一个上传者和一张最新帧。"""

    session: Session
    view: VisualView
    uploader: WebSocket | None = None
    hello: bool = False
    packet: bytes | None = None
    received_at: float | None = None
    selection_started_at: float | None = None
    last_stream_id: str | None = None
    last_sequence: int = 0
    subscribers: dict[asyncio.Queue, WebSocket] = field(default_factory=dict)


class VisualService:
    """依附执行会话，画面失败不会关闭工具执行通道。"""

    def __init__(self, *, sessions: SessionService):
        self.sessions = sessions
        self.channels: dict[str, VisualChannel] = {}
        self.task: asyncio.Task | None = None

    def active(self, *, session: Session) -> bool:
        """确认当前代次、租期和控制连接仍有效。"""
        live = self.sessions.nodes.connections.get(session.view.node_id)
        now = datetime.now(UTC)
        return (session.view.state == "ACTIVE" and session.view.expires_at > now and live is session.connection
                and (now - live.last_seen_at).total_seconds() < self.sessions.nodes.settings.heartbeat_timeout_seconds)

    def supported(self, *, view: SessionView) -> bool:
        """按当前 Node 的真实后端声明判断画面支持。"""
        live = self.sessions.nodes.connections.get(view.node_id)
        if live is None or live.capabilities is None:
            return False
        return any(item.name == view.backend and VISUAL_PROTOCOL in item.declared_protocols for item in live.capabilities.backends)

    def channel(self, *, session: Session) -> VisualChannel:
        """创建临时通道；不修改或持久化会话视图。"""
        return self.channels.setdefault(session.view.session_id, VisualChannel(session=session, view=VisualView(
            supported=True, state="WAITING", reason_code="VISUAL_UPLOAD_PENDING",
            stream_path=f"/v1/sessions/{session.view.session_id}/visual/stream")))

    def snapshot(self, *, channel: VisualChannel) -> VisualView:
        """图片和来源一起取快照，帧龄使用 Hub 单调时钟。"""
        value = channel.view.model_copy(deep=True)
        if channel.received_at is not None:
            value.frame_age_ms = max(0, int((monotonic() - channel.received_at) * 1000))
        return value

    def describe(self, *, view: SessionView) -> VisualView:
        """查询接口使用当前状态，不返回过期的可连接入口。"""
        supported = self.supported(view=view)
        if view.state in TERMINAL or view.state == "CLOSING":
            return VisualView(supported=supported, state="STOPPED", reason_code=view.close_reason or "SESSION_FINISHED")
        session = self.sessions.sessions.get(view.session_id)
        if session is None or self.sessions.nodes.connections.get(view.node_id) is not session.connection:
            return VisualView(supported=supported, reason_code="NODE_OFFLINE")
        if not supported:
            return VisualView(reason_code="EXTENSION_NOT_ADVERTISED")
        if view.state != "ACTIVE":
            return VisualView(supported=True, state="WAITING", reason_code="SESSION_NOT_ACTIVE")
        if not self.active(session=session):
            return VisualView(supported=True, reason_code="NODE_OFFLINE")
        channel = self.channel(session=session)
        self.refresh(channel=channel)
        return self.snapshot(channel=channel)

    async def node_view(self, *, view: NodeView, token: str | None) -> NodeVisualView:
        """只列出当前许可创建的活动流，不能从资源权限推导会话权限。"""
        grant = await self.sessions.nodes.authorize_access(node_id=view.node_id, token=token)
        result = NodeVisualView(supported=bool(view.capabilities and any(
            VISUAL_PROTOCOL in item.declared_protocols for item in view.capabilities.backends)))
        allowed = {item.resource_id for item in view.capabilities.resources} if view.capabilities else set()
        for session in list(self.sessions.sessions.values()):
            item = session.view
            if (item.node_id == view.node_id and item.grant_id == grant["grant_id"] and item.resource_id in allowed
                    and self.active(session=session) and self.supported(view=item)):
                result.streams.append(VisualStreamView(session_id=item.session_id, resource_id=item.resource_id,
                                                     **self.describe(view=item).model_dump()))
        if result.streams:
            result.supported = True
        return result

    def publish(self, *, channel: VisualChannel) -> None:
        """替换各订阅者的待发帧，不等待网络写入。"""
        update = (self.snapshot(channel=channel), channel.packet if channel.view.state == "LIVE" else None)
        for queue in channel.subscribers:
            if queue.full():
                queue.get_nowait()
            queue.put_nowait(update)

    def clear(self, *, channel: VisualChannel) -> None:
        """丢弃旧帧和旧流来源。"""
        channel.packet = None
        channel.received_at = None
        channel.view.stream_id = None
        channel.view.target_id = None
        channel.view.last_frame_id = None
        channel.view.capture_started_at = None

    def refresh(self, *, channel: VisualChannel) -> None:
        """检查新鲜度和目标切换超时，与客户端墙钟无关。"""
        changed = False
        if channel.view.state == "LIVE" and channel.received_at is not None and monotonic() - channel.received_at > STALE_SECONDS:
            channel.packet = None
            channel.view.state = "STALE"
            channel.view.reason_code = "FRAME_STALE"
            changed = True
        if (channel.view.selection and channel.view.selection.state == "PENDING" and channel.selection_started_at is not None
                and monotonic() - channel.selection_started_at > SELECTION_SECONDS):
            channel.view.selection.state = "FAILED"
            channel.view.selection.error_code = "TARGET_SELECTION_TIMEOUT"
            self.clear(channel=channel)
            channel.view.state = "ERROR"
            channel.view.reason_code = "TARGET_SELECTION_TIMEOUT"
            changed = True
        if changed:
            self.publish(channel=channel)

    async def attach(self, *, node_id: str, session_id: str, generation: int, token: str | None, websocket: WebSocket) -> VisualChannel:
        """上传认证独立于执行连接，只允许当前活动会话。"""
        await self.sessions.nodes.authorize_owner(node_id=node_id, token=token)
        async with self.sessions.nodes.lock:
            session = self.sessions.sessions.get(session_id)
            if session is None or session.view.node_id != node_id or session.view.connection_generation != generation:
                raise ServiceError(status=409, code="STALE_SESSION")
            if not self.active(session=session):
                raise ServiceError(status=410, code="SESSION_NOT_ACTIVE")
            if not self.supported(view=session.view):
                raise ServiceError(status=409, code="VISUAL_UNSUPPORTED")
            channel = self.channel(session=session)
            if channel.uploader is not None:
                raise ServiceError(status=409, code="VISUAL_UPLOAD_BUSY")
            await websocket.accept()
            self.clear(channel=channel)
            channel.uploader = websocket
            channel.hello = False
            channel.view.state = "WAITING"
            channel.view.reason_code = "SCREENSHOT_NOT_READY"
            return channel

    def check_upload(self, *, channel: VisualChannel, websocket: WebSocket) -> None:
        """每次接收都复核归属，旧上传者不能覆盖新连接。"""
        if channel.uploader is not websocket or not self.active(session=channel.session):
            raise ServiceError(status=409, code="STALE_SESSION")

    def targets(self, *, channel: VisualChannel, values: list[VisualTarget]) -> None:
        """目标变更及时移除已关闭页面的旧图。"""
        if len({item.target_id for item in values}) != len(values):
            raise ValueError("重复的画面目标")
        channel.view.targets = values
        selection = channel.view.selection
        if selection is not None and selection.state == "PENDING" and selection.target_id not in {item.target_id for item in values}:
            selection.state = "FAILED"
            selection.error_code = "TARGET_CLOSED"
        if channel.view.target_id and channel.view.target_id not in {item.target_id for item in values}:
            self.clear(channel=channel)
            channel.view.state = "WAITING_TARGET"
            channel.view.reason_code = "TARGET_CLOSED"
        self.publish(channel=channel)

    def source_state(self, *, channel: VisualChannel, message: VisualSourceState) -> None:
        """切换确认必须匹配当前请求，迟到确认和旧流不重新生效。"""
        selection = channel.view.selection
        if message.request_id is not None:
            if selection is None or selection.request_id != message.request_id or selection.state == "FAILED":
                return
            if selection.state == "APPLIED" and (message.stream_id != channel.last_stream_id or message.target_id != selection.target_id):
                return
            if message.state == "ERROR" and selection.state == "PENDING":
                selection.state = "FAILED"
                selection.error_code = message.reason_code or "TARGET_SELECTION_FAILED"
            elif message.target_id != selection.target_id:
                raise ValueError("画面目标确认不一致")
        elif selection is not None and selection.state == "PENDING":
            return
        if bool(message.stream_id) != bool(message.target_id):
            raise ValueError("画面流与目标须同时提供")
        if message.target_id is not None and message.target_id not in {item.target_id for item in channel.view.targets}:
            raise ValueError("画面目标不在当前目录")
        self.clear(channel=channel)
        channel.view.state = message.state
        channel.view.stream_id = message.stream_id
        channel.view.target_id = message.target_id
        channel.view.reason_code = message.reason_code
        self.publish(channel=channel)

    def frame(self, *, channel: VisualChannel, metadata: VisualFrame, data: bytes) -> None:
        """仅接受当前流的递增帧，由实际图片确认 LIVE。"""
        view = channel.session.view
        if (metadata.session_id, metadata.resource_id, metadata.connection_generation) != (view.session_id, view.resource_id, view.connection_generation):
            raise ValueError("画面归属无效")
        if (metadata.stream_id, metadata.target_id) != (channel.view.stream_id, channel.view.target_id):
            return
        if channel.last_stream_id == metadata.stream_id and metadata.frame_id <= channel.last_sequence:
            return
        selection = channel.view.selection
        if selection is not None and selection.state == "PENDING":
            selection.state = "APPLIED"
        channel.packet = data
        channel.last_stream_id = metadata.stream_id
        channel.last_sequence = metadata.frame_id
        channel.received_at = monotonic()
        channel.view.last_frame_id = metadata.frame_id
        channel.view.capture_started_at = metadata.capture_started_at
        channel.view.state = "LIVE"
        channel.view.reason_code = None
        self.publish(channel=channel)

    async def select(self, *, session_id: str, target_id: str) -> VisualSelection:
        """串行受理选择，首张新图才完成切换。"""
        channel = self.channels.get(session_id)
        if channel is None or not channel.hello or channel.uploader is None or not self.active(session=channel.session):
            raise ServiceError(status=409, code="VISUAL_UPLOAD_NOT_READY")
        self.refresh(channel=channel)
        if channel.view.selection is not None and channel.view.selection.state == "PENDING":
            raise ServiceError(status=409, code="TARGET_SELECTION_PENDING")
        if target_id not in {item.target_id for item in channel.view.targets}:
            raise ServiceError(status=404, code="VISUAL_TARGET_NOT_FOUND")
        selection = VisualSelection(request_id=f"select_{uuid4().hex}", target_id=target_id)
        channel.view.selection = selection
        channel.selection_started_at = monotonic()
        self.clear(channel=channel)
        channel.view.state = "WAITING"
        channel.view.reason_code = "TARGET_SELECTION_PENDING"
        self.publish(channel=channel)
        try:
            await asyncio.wait_for(channel.uploader.send_json({"type": "select_target", "request_id": selection.request_id, "target_id": target_id}), timeout=2)
        except (OSError, RuntimeError, TimeoutError):
            selection.state = "FAILED"
            selection.error_code = "VISUAL_UPLOAD_DISCONNECTED"
            self.publish(channel=channel)
            raise ServiceError(status=503, code="VISUAL_UPLOAD_DISCONNECTED") from None
        return selection.model_copy(deep=True)

    async def close(self, *, session_id: str, reason: str) -> None:
        """会话关闭先撤销画面，再限时关闭上传和订阅。"""
        channel = self.channels.pop(session_id, None)
        if channel is None:
            return
        self.clear(channel=channel)
        channel.view.state = "STOPPED"
        channel.view.stream_path = None
        channel.view.reason_code = reason
        self.publish(channel=channel)
        await asyncio.gather(*(close_websocket(websocket=socket, reason=reason)
                               for socket in [channel.uploader, *channel.subscribers.values()] if socket is not None))

    def detach(self, *, channel: VisualChannel, websocket: WebSocket) -> None:
        """断开仅影响画面，晚到的旧连接清理不覆盖新上传者。"""
        if channel.uploader is websocket:
            channel.uploader = None
            channel.hello = False
            self.clear(channel=channel)
            if channel.view.state != "STOPPED":
                channel.view.state = "ERROR"
                channel.view.reason_code = "VISUAL_UPLOAD_DISCONNECTED"
                self.publish(channel=channel)

    async def start(self) -> None:
        """启动单个新鲜度检查任务。"""
        async def maintain():
            while True:
                await asyncio.sleep(delay=0.25)
                for key, channel in list(self.channels.items()):
                    if not self.active(session=channel.session):
                        await self.close(session_id=key, reason="SESSION_NOT_ACTIVE")
                    else:
                        self.refresh(channel=channel)
        self.task = asyncio.create_task(coro=maintain(), name="runbridge-visual-maintenance")

    async def shutdown(self) -> None:
        """服务结束不恢复图片缓存。"""
        if self.task is not None:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for key in list(self.channels):
            await self.close(session_id=key, reason="HUB_RESTARTED")
