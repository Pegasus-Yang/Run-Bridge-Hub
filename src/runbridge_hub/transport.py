"""把控制连接的 WebSocket Ping/Pong 实测结果提供给只读总览。"""

import asyncio
import time
from datetime import UTC, datetime

from uvicorn.protocols.websockets.websockets_impl import WebSocketProtocol
from websockets.exceptions import ConnectionClosed


RTT_MAX_AGE_SECONDS = 60


class ControlWebSocketProtocol(WebSocketProtocol):
    """复用 Uvicorn 的保活 Ping，不改变 Node 的应用消息合同。"""

    async def run_asgi(self) -> None:
        """为控制连接注册进程内 RTT 读取扩展。"""
        path = self.scope["path"]
        self._measure_rtt = path.startswith("/v2/nodes/") and path.endswith("/control")
        self._rtt_sample = None
        if self._measure_rtt:
            self.scope.setdefault("extensions", {})["runbridge.control_rtt"] = self.read_rtt
        await super().run_asgi()

    async def keepalive_ping(self) -> None:
        """连接建立后立即测一次，后续沿用服务端保活周期。"""
        if self.ping_interval is not None and self._measure_rtt:
            try:
                await self.ping()
            except ConnectionClosed:
                return
        await super().keepalive_ping()

    async def ping(self, data=None):
        """记录与本次 Ping 对应的 Pong 耗时。

        :param data: 底层协议的可选 Ping 载荷。
        :returns: 底层 Pong 等待对象。
        """
        waiter = await super().ping(data=data)
        if self._measure_rtt:
            waiter.add_done_callback(self._record_pong)
        return waiter

    def _record_pong(self, waiter: asyncio.Future) -> None:
        """仅记录成功完成的测量，断线不会生成零延迟。

        :param waiter: 收到对应 Pong 后完成的 Future。
        """
        if waiter.cancelled() or waiter.exception() is not None:
            return
        self._rtt_sample = (waiter.result() * 1000, datetime.now(UTC), time.monotonic())

    def read_rtt(self) -> dict:
        """读取最后一次测量，使用单调时钟判断是否过期。

        :returns: 测量状态、毫秒耗时、采样时间和样本年龄。
        """
        if self._rtt_sample is None:
            return {"status": "PENDING", "rtt_ms": None, "measured_at": None, "sample_age_ms": None}
        milliseconds, measured_at, observed = self._rtt_sample
        age = max(0, time.monotonic() - observed)
        return {
            "status": "MEASURED" if age < RTT_MAX_AGE_SECONDS else "STALE",
            "rtt_ms": round(milliseconds, 3) if age < RTT_MAX_AGE_SECONDS else None,
            "measured_at": measured_at,
            "sample_age_ms": int(age * 1000),
        }
