"""单 Worker 服务启动后输出总览的实际访问地址。"""

import socket

import uvicorn

from runbridge_hub.dashboard import log_access


class HubServer(uvicorn.Server):
    """在完成应用初始化和端口绑定后输出只读访问入口。"""

    async def startup(self, sockets: list[socket.socket] | None = None) -> None:
        """使用实际套接字端口生成链接，兼容系统分配的临时端口。

        :param sockets: 可选的预绑定套接字。
        """
        await super().startup(sockets=sockets)
        if not self.started:
            return
        token = getattr(self.config.app.state, "web_token", None)
        if token is not None:
            host, port = self.servers[0].sockets[0].getsockname()[:2]
            log_access(
                token=token, host=host, port=port,
                scheme="https" if self.config.is_ssl else "http",
            )
