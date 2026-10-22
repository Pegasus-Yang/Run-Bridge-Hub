"""节点总览的独立只读鉴权与真实状态投影。"""

import logging
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal
from urllib.parse import urlencode

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, SecretStr

from runbridge_hub import __version__
from runbridge_hub.protocol import NodeView
from runbridge_hub.security import bearer_token, generate_token_file, matches
from runbridge_hub.service import ServiceError
from runbridge_hub.settings import HubSettings


router = APIRouter(prefix="/dashboard")
ASSET_DIRECTORY = Path(__file__).parent / "web"
logger = logging.getLogger("uvicorn.error")
WEB_HEADERS = {
    "Cache-Control": "no-store",
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self'; connect-src 'self'; base-uri 'none'; form-action 'self'; frame-ancestors 'none'",
}


class LatencyView(BaseModel):
    """控制链路 RTT 与应用心跳分开呈现。"""

    status: Literal["PENDING", "MEASURED", "STALE", "UNAVAILABLE", "OFFLINE"]
    rtt_ms: float | None = None
    measured_at: datetime | None = None
    sample_age_ms: int | None = None


class ResourceCounts(BaseModel):
    """只将在线且已就绪、未占用的资源计为可用。"""

    total: int = 0
    available: int = 0
    busy: int = 0
    unknown: int = 0
    unavailable: int = 0


class DashboardNode(NodeView):
    """完整节点状态及总览统计，不包含凭据和业务载荷。"""

    latency: LatencyView
    resources: ResourceCounts


class Overview(BaseModel):
    """一次查询得到的一致统计和节点列表。"""

    snapshot_at: datetime
    hub_version: str
    refresh_interval_seconds: int = 5
    nodes: list[DashboardNode]
    total: int
    online: int
    preparing: int
    offline: int
    resources: ResourceCounts


def initialize_access(*, settings: HubSettings) -> SecretStr:
    """准备独立只读口令，首次启动自动保存。

    :param settings: 已验证的 Hub 配置。
    :returns: 供鉴权和启动访问日志使用的只读口令。
    """
    if settings.web_token is not None:
        token = settings.web_token.get_secret_value()
        logger.info("节点总览已启用：/dashboard；使用配置的独立只读口令")
    else:
        path = settings.database_path.parent / "web.token"
        if not path.exists():
            generate_token_file(path=path)
        token = path.read_text(encoding="utf-8").strip()
        logger.info("节点总览已启用：/dashboard；只读口令文件：%s", path.resolve())
    if not 32 <= len(token) <= 256:
        raise ValueError("总览只读口令长度必须为 32～256 字符")
    if token == settings.enrollment_token.get_secret_value():
        raise ValueError("总览只读口令必须与登记凭据不同")
    return SecretStr(secret_value=token)


def log_access(*, token: SecretStr, host: str, port: int, scheme: str = "http") -> None:
    """输出只读口令及可直接点击的总览链接。

    :param token: 当前只读口令。
    :param host: 实际监听地址，通配地址转换为本机回环地址。
    :param port: 实际绑定端口。
    :param scheme: HTTP 协议。
    """
    host = {"0.0.0.0": "127.0.0.1", "::": "::1"}.get(host, host)
    authority = f"[{host}]" if ":" in host else host
    value = token.get_secret_value()
    query = urlencode(query={"token": value})
    logger.info("Dashboard 只读口令：%s", value)
    logger.info("Dashboard URL：%s://%s:%s/dashboard?%s", scheme, authority, port, query)


@router.get("", include_in_schema=False)
@router.get("/", include_in_schema=False)
async def page():
    """返回登录及节点总览界面，节点数据由受保护接口提供。

    :returns: 本地打包的页面。
    """
    return FileResponse(path=ASSET_DIRECTORY / "index.html", headers=WEB_HEADERS)


@router.get("/api/nodes", response_model=Overview)
async def nodes(request: Request, response: Response, authorization: str | None = Header(default=None)):
    """验证总览口令，返回当前连接、资源预留与控制链路实测值。

    :returns: 不含身份凭据、许可或会话载荷的节点总览。
    """
    response.headers.update(WEB_HEADERS)
    token = bearer_token(header=authorization)
    if token is None or not matches(token=token, expected_hash=request.app.state.web_token_digest):
        raise ServiceError(status=401, code="INVALID_WEB_TOKEN")
    service = request.app.state.service
    views = await service.overview()
    result = []
    totals = ResourceCounts()
    for view in views:
        counts = ResourceCounts()
        for resource in view.capabilities.resources if view.capabilities else []:
            counts.total += 1
            if view.connection_status != "ONLINE" or resource.occupancy == "UNKNOWN":
                counts.unknown += 1
            elif resource.occupancy == "BUSY":
                counts.busy += 1
            elif resource.readiness == "READY":
                counts.available += 1
            else:
                counts.unavailable += 1
        if view.connection_status == "ONLINE":
            for field in ResourceCounts.model_fields:
                setattr(totals, field, getattr(totals, field) + getattr(counts, field))
        connection = service.connections.get(view.node_id)
        if view.connection_status == "OFFLINE":
            latency = LatencyView(status="OFFLINE")
        elif connection is not None and callable(connection.control_rtt):
            latency = LatencyView.model_validate(connection.control_rtt())
        else:
            latency = LatencyView(status="UNAVAILABLE")
        result.append(DashboardNode(**view.model_dump(), latency=latency, resources=counts))
    return Overview(
        snapshot_at=datetime.now(UTC), hub_version=__version__, nodes=result,
        total=len(result), online=sum(node.connection_status == "ONLINE" for node in result),
        preparing=sum(node.connection_status == "PREPARING" for node in result),
        offline=sum(node.connection_status == "OFFLINE" for node in result), resources=totals,
    )
