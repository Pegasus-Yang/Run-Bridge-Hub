"""MCP 逐请求鉴权与工具参数适配；浏览器操作全部由 Node 执行。"""

import base64
import json
from contextvars import ContextVar
from functools import wraps
from typing import Annotated, Literal

from mcp.server import MCPServer
from mcp.server.transport_security import TransportSecuritySettings
from mcp_types import CallToolResult, ImageContent, TextContent, ToolAnnotations
from pydantic import Field, SecretStr
from starlette.datastructures import Headers
from starlette.responses import JSONResponse, Response

from runbridge_hub import __version__
from runbridge_hub.browser import BrowserError
from runbridge_hub.browser_tools import Target, object_target, register_tools
from runbridge_hub.protocol import Identifier
from runbridge_hub.security import bearer_token
from runbridge_hub.service import ServiceError
from runbridge_hub.settings import HubSettings


REQUEST_TOKEN: ContextVar[SecretStr] = ContextVar("runbridge_mcp_token")
Timeout = Annotated[int, Field(ge=1, le=30000)]
Lease = Annotated[float, Field(ge=1, le=3600)]
HTTP_REQUEST_LIMIT = 8 * 1024 * 1024


def header_allowed(*, value: str | None, allowed: list[str]) -> bool:
    """按精确值或任意端口匹配 MCP 的 Host/Origin。

    :param value: 请求头原值。
    :param allowed: 允许值列表。
    :returns: 是否匹配。
    """
    return value is not None and (
        value in allowed
        or any(
            pattern.endswith(":*") and value.startswith(pattern[:-1])
            for pattern in allowed
        )
    )


def result(
    *, values: dict, error: bool = False, image: bytes | None = None
) -> CallToolResult:
    content = [TextContent(text=json.dumps(values, ensure_ascii=False))]
    if image is not None:
        content.append(
            ImageContent(data=base64.b64encode(image).decode(), mime_type="image/png")
        )
    return CallToolResult(content=content, structured_content=values, is_error=error)


class BearerMiddleware:
    def __init__(self, *, app, hub, settings: HubSettings):
        self.app = app
        self.hub = hub
        self.settings = settings

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        token = bearer_token(header=headers.get("authorization"))
        if token is not None and len(token) > 256:
            token = None
        try:
            await self.hub.state.service.resolve_access(token=token)
        except ServiceError as error:
            await JSONResponse(
                status_code=401,
                content={"code": error.code},
                headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
            )(scope, receive, send)
            return
        if self.settings.mcp_allowed_hosts and not header_allowed(
            value=headers.get("host"), allowed=self.settings.mcp_allowed_hosts
        ):
            await Response(content="Invalid Host header", status_code=421)(
                scope, receive, send
            )
            return
        origin = headers.get("origin")
        if origin and not header_allowed(
            value=origin, allowed=self.settings.mcp_allowed_origins
        ):
            await Response(content="Invalid Origin header", status_code=403)(
                scope, receive, send
            )
            return
        context = REQUEST_TOKEN.set(SecretStr(token))
        try:
            await self.app(scope, receive, send)
        finally:
            REQUEST_TOKEN.reset(context)


def build_mcp(*, hub, settings: HubSettings):
    server = MCPServer(
        name="RunBridge Browser",
        version=__version__,
        instructions="通过 node_id 选择节点，保存 session_id/page_id。动作在 Node 的 Python 工具中执行。完成后 browser_stop 并检查 cleanup。写入结果未知时先观察，禁止盲目重试。",
    )

    def token():
        return REQUEST_TOKEN.get().get_secret_value()

    def browsers():
        return hub.state.browsers

    def tool(*, readonly=False, idempotent=False):
        def decorate(function):
            @wraps(function)
            async def invoke(*args, **kwargs):
                try:
                    value = await function(*args, **kwargs)
                    return (
                        value
                        if isinstance(value, CallToolResult)
                        else result(values=value)
                    )
                except ServiceError as error:
                    return result(
                        values={
                            "code": error.code,
                            "execution_outcome": getattr(
                                error, "outcome", "NOT_STARTED"
                            ),
                            "request_id": getattr(error, "request_id", None),
                        },
                        error=True,
                    )

            server.tool(
                structured_output=False,
                annotations=ToolAnnotations(
                    read_only_hint=readonly,
                    destructive_hint=not readonly,
                    idempotent_hint=idempotent,
                    open_world_hint=True,
                ),
            )(invoke)
            return invoke

        return decorate

    async def call(*, session_id, page_id, method, params=None, target=None):
        return await browsers().call(
            session_id=session_id,
            token=token(),
            method=method,
            target=object_target(page_id=page_id, target=target),
            params=params or {},
        )

    @tool(readonly=True, idempotent=True)
    async def node_inspect(node_id: Identifier) -> dict:
        """查询授权节点的真实能力、就绪与占用状态。"""
        return (
            await hub.state.service.query(node_id=node_id, token=token())
        ).model_dump(mode="json")

    @tool()
    async def browser_start(
        node_id: Identifier,
        resource_id: Identifier | None = None,
        lease_seconds: Lease = 300,
        request_id: Identifier | None = None,
    ) -> dict:
        """启动远程受管理 Chromium 和空白页，保存返回的会话、页面及 request_id。"""
        return await browsers().open(
            node_id=node_id,
            token=token(),
            resource_id=resource_id,
            lease_seconds=lease_seconds,
            request_id=request_id,
        )

    @tool(readonly=True, idempotent=True)
    async def browser_sessions(
        node_id: Identifier, request_id: Identifier | None = None
    ) -> dict:
        """查询当前许可的会话，按启动 request_id 找回分配结果。"""
        return await browsers().listing(
            node_id=node_id, token=token(), request_id=request_id
        )

    @tool(readonly=True, idempotent=True)
    async def browser_status(session_id: Identifier) -> dict:
        """读取 Node 同步的页面目录、会话和画面状态。"""
        return await browsers().status(session_id=session_id, token=token())

    @tool(idempotent=True)
    async def browser_stop(session_id: Identifier) -> dict:
        """释放并检查真实 cleanup；重复释放不重新启动资源。"""
        return {
            "session": (
                await hub.state.sessions.release(session_id=session_id, token=token())
            ).model_dump(mode="json")
        }

    @tool(readonly=True, idempotent=True)
    async def tool_request_status(
        session_id: Identifier, request_id: Identifier
    ) -> CallToolResult:
        """查询已提交指令的状态和结果，不重放动作。"""
        value = await hub.state.commands.query(
            session_id=session_id, request_id=request_id, token=token()
        )
        data = value.get("result")
        if data and data["kind"] == "binary":
            return result(
                values={
                    **value,
                    "result": {
                        key: item for key, item in data.items() if key != "data"
                    },
                },
                image=base64.b64decode(data["data"]),
            )
        return result(values=value, error=value["status"] in {"FAILED", "UNKNOWN"})

    @tool()
    async def browser_navigate(
        session_id: Identifier,
        page_id: Identifier,
        url: Annotated[str, Field(max_length=8192)],
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """在 Node 导航并等待 DOM 就绪，返回实际 url/title/http_status。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="page.goto",
            params={"url": url, "timeout": timeout_ms},
        )

    @tool(readonly=True, idempotent=True)
    async def browser_snapshot(
        session_id: Identifier, page_id: Identifier, timeout_ms: Timeout = 10000
    ) -> dict:
        """Node 读取实际语义快照，最多 20000 字符。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="page.aria_snapshot",
            params={"timeout": timeout_ms},
        )

    @tool()
    async def browser_fill(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        value: Annotated[str, Field(max_length=20000)],
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """填写唯一匹配控件；需再次读取验证业务效果。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.fill",
            target=target,
            params={"value": value, "timeout": timeout_ms},
        )

    @tool()
    async def browser_click(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """点击唯一匹配元素；completed 仅表示动作完成。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.click",
            target=target,
            params={"timeout": timeout_ms},
        )

    @tool(readonly=True, idempotent=True)
    async def browser_read(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        kind: Literal["text", "input_value"] = "text",
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """读取唯一元素的真实文本或输入值，最多 20000 字符。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.inner_text" if kind == "text" else "locator.input_value",
            target=target,
            params={"timeout": timeout_ms},
        )

    @tool(readonly=True, idempotent=True)
    async def browser_wait_for(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        state: Literal[
            "visible", "hidden", "attached", "detached", "text", "value"
        ] = "visible",
        value: Annotated[str | None, Field(max_length=20000)] = None,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """等待实际状态或完整值，不用固定休眠替代。"""
        params = {"state": state, "timeout": timeout_ms}
        method = "locator.wait_for"
        if state in {"text", "value"}:
            if value is None:
                raise BrowserError(code="EXPECTED_VALUE_REQUIRED")
            params["value"] = value
            method = "runbridge.wait_for"
        response = await call(
            session_id=session_id,
            page_id=page_id,
            method=method,
            target=target,
            params=params,
        )
        return {"matched": True, "request_id": response["request_id"]}

    @tool(readonly=True, idempotent=True)
    async def browser_screenshot(
        session_id: Identifier,
        page_id: Identifier,
        full_page: bool = False,
        timeout_ms: Timeout = 10000,
    ) -> CallToolResult:
        """由 Node 截取 PNG，通过 MCP 图像内容返回，最大 2 MiB。"""
        value = await call(
            session_id=session_id,
            page_id=page_id,
            method="page.screenshot",
            params={"full_page": full_page, "timeout": timeout_ms},
        )
        return result(
            values={
                "mime_type": value["mime_type"],
                "bytes": value["size"],
                "request_id": value["request_id"],
            },
            image=base64.b64decode(value["data"], validate=True),
        )

    register_tools(tool=tool, browsers=browsers, token=token)
    app = server.streamable_http_app(
        streamable_http_path="/mcp",
        json_response=True,
        stateless_http=True,
        max_request_body_size=HTTP_REQUEST_LIMIT,
        transport_security=TransportSecuritySettings(
            # SDK 的统一开关不能独立放开 Host，头部规则由外层分别校验。
            enable_dns_rebinding_protection=False,
        ),
    )
    return server, BearerMiddleware(app=app, hub=hub, settings=settings)
