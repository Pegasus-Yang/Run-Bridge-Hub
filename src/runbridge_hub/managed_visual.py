"""从 MCP 已持有的同一 Page 采集画面，不增加原生执行客户端。"""

import asyncio
import base64
from contextlib import suppress
from datetime import UTC, datetime
from time import monotonic
from uuid import uuid4

from playwright.async_api import Error

from runbridge_hub.service import ServiceError
from runbridge_hub.visual_protocol import VisualFrame, VisualSelection, VisualTarget
from runbridge_hub.visual_wire import pack_frame


class ManagedCapture:
    """每会话一个有界采集任务，目标使用 MCP 的不透明页面 ID。"""

    def __init__(self, *, visual, session, entry):
        self.visual = visual
        self.session = session
        self.entry = entry
        self.channel = visual.channel(session=session)
        self.channel.source = self
        self.channel.hello = True
        self.task = None
        self.generation = 0
        self.closed = False
        self.selection_lock = asyncio.Lock()

    async def select(self, *, target_id: str) -> VisualSelection:
        """先撤下旧图，再采集明确页面；第一张新图才确认选择。

        :returns: 本次选择的待确认状态。
        """
        async with self.selection_lock:
            if self.closed:
                raise ServiceError(status=409, code="VISUAL_SESSION_NOT_ACTIVE")
            page = self.entry.pages.get(target_id)
            if page is None or page.is_closed():
                raise ServiceError(status=404, code="VISUAL_TARGET_NOT_FOUND")
            self.generation += 1
            generation = self.generation
            if self.task:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
            channel = self.channel
            self.visual.clear(channel=channel)
            channel.view.target_id = target_id
            channel.view.stream_id = f"stream_{uuid4().hex}"
            channel.view.selection = VisualSelection(request_id=f"select_{uuid4().hex}", target_id=target_id)
            channel.selection_started_at = monotonic()
            channel.view.state = "WAITING"
            channel.view.reason_code = "SCREENSHOT_NOT_READY"
            self.visual.publish(channel=channel)
            self.task = asyncio.create_task(self.capture(page=page, target_id=target_id, generation=generation, stream_id=channel.view.stream_id))
            return channel.view.selection.model_copy(deep=True)

    async def capture(self, *, page, target_id: str, generation: int, stream_id: str) -> None:
        """固定只读 CDP 截图独立于页面操作锁，最新帧覆盖旧帧。"""
        cdp = None
        sequence = 0
        try:
            cdp = await page.context.new_cdp_session(page=page)
            while not self.closed and generation == self.generation and self.visual.active(session=self.session):
                channel = self.channel
                self.visual.targets(channel=channel, values=[VisualTarget(target_id=key, label=f"页面 {index + 1}") for index, key in enumerate(list(self.entry.pages))])
                if self.entry.pages.get(target_id) is not page or page.is_closed():
                    self.visual.clear(channel=channel)
                    channel.view.state = "WAITING_TARGET"
                    channel.view.reason_code = "TARGET_CLOSED"
                    self.visual.publish(channel=channel)
                    return
                started = datetime.now(UTC)
                try:
                    async with asyncio.timeout(delay=3):
                        result = await cdp.send(method="Page.captureScreenshot", params={"format": "png", "captureBeyondViewport": False})
                    png = base64.b64decode(result["data"], validate=True)
                    if self.closed or generation != self.generation or not self.visual.active(session=self.session):
                        return
                    if channel.view.selection and channel.view.selection.state == "FAILED":
                        return
                    # 短暂采集错误会撤下公开来源，重试成功后恢复本任务的明确绑定。
                    channel.view.target_id = target_id
                    channel.view.stream_id = stream_id
                    sequence += 1
                    view = self.session.view
                    metadata = VisualFrame(connection_generation=view.connection_generation, session_id=view.session_id, resource_id=view.resource_id, stream_id=stream_id, target_id=target_id, frame_id=sequence, capture_started_at=started)
                    packet = pack_frame(metadata=metadata, png=png)
                    self.visual.frame(channel=channel, metadata=metadata, data=packet)
                except (Error, ValueError, KeyError, TimeoutError):
                    if self.closed or generation != self.generation:
                        return
                    self.visual.clear(channel=channel)
                    channel.view.state = "ERROR"
                    channel.view.reason_code = "CAPTURE_FAILED"
                    self.visual.publish(channel=channel)
                await asyncio.sleep(delay=0.3)
        except (Error, TimeoutError):
            if not self.closed and generation == self.generation:
                self.visual.clear(channel=self.channel)
                self.channel.view.state = "ERROR"
                self.channel.view.reason_code = "CAPTURE_FAILED"
                self.visual.publish(channel=self.channel)
        finally:
            if cdp:
                with suppress(Error, TimeoutError):
                    await asyncio.wait_for(cdp.detach(), timeout=2)

    async def close(self) -> None:
        """失效任务与代次，不改变 Node 报告的清理结论。"""
        async with self.selection_lock:
            self.closed = True
            self.generation += 1
            if self.task:
                self.task.cancel()
                await asyncio.gather(self.task, return_exceptions=True)
                self.task = None
