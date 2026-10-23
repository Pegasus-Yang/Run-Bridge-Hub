"""单实例 Hub 的 ASGI 应用工厂。"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.staticfiles import StaticFiles

from runbridge_hub import __version__

from runbridge_hub.api import router as management_router
from runbridge_hub.api import execution_router
from runbridge_hub.commands import CommandService, router as commands_router
from runbridge_hub.leases import LeaseService
from runbridge_hub.body_limit import RequestSizeLimit
from runbridge_hub.gateway import router as gateway_router
from runbridge_hub.service import NodeService, ServiceError
from runbridge_hub.sessions import SessionService
from runbridge_hub.native import router as native_router
from runbridge_hub.settings import HubSettings
from runbridge_hub.security import token_hash
from runbridge_hub.store import Store
from runbridge_hub.visual import VisualService
from runbridge_hub.visual_api import router as visual_router
from runbridge_hub.dashboard import ASSET_DIRECTORY, initialize_access, router as dashboard_router


def create_app(*, settings: HubSettings) -> FastAPI:
    """创建具有独立内存状态的单 Worker 应用。

    :param settings: 运行配置。
    :returns: ASGI 应用。
    """
    mcp = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if settings.web_enabled:
            app.state.web_token = initialize_access(settings=settings)
            app.state.web_token_digest = token_hash(token=app.state.web_token.get_secret_value())
        store = Store(path=settings.database_path)
        await store.open()
        service = NodeService(store=store, settings=settings)
        app.state.service = service
        sessions = SessionService(nodes=service)
        app.state.sessions = sessions
        leases = LeaseService(nodes=service, sessions=sessions)
        service.leases = leases
        app.state.leases = leases
        visual = VisualService(sessions=sessions)
        app.state.visual = visual
        sessions.on_close = visual.close
        service.on_disconnect = sessions.interrupt_node
        await sessions.start()
        commands = CommandService(sessions=sessions)
        app.state.commands = commands
        await commands.start()
        async def close_session(*, session_id: str, reason: str):
            await asyncio.gather(visual.close(session_id=session_id, reason=reason), commands.closed(session_id=session_id, reason=reason))
        sessions.on_close = close_session
        await visual.start()
        await leases.start()
        browsers = None
        try:
            async with AsyncExitStack() as stack:
                if mcp is not None:
                    from runbridge_hub.browser import BrowserService

                    browsers = BrowserService(sessions=sessions, commands=commands, visual=visual)
                    app.state.browsers = browsers

                    await browsers.start()
                    await stack.enter_async_context(mcp.session_manager.run())
                yield
        finally:
            if browsers is not None:
                await browsers.shutdown()
            await sessions.shutdown()
            await commands.shutdown()
            await visual.shutdown()
            await leases.shutdown()
            await service.close()
            await store.close()

    app = FastAPI(title="RunBridge Hub", version=__version__, lifespan=lifespan)
    app.add_middleware(RequestSizeLimit)
    app.include_router(management_router)
    app.include_router(execution_router)
    app.include_router(commands_router)
    app.include_router(gateway_router)
    app.include_router(native_router)
    app.include_router(visual_router)
    if settings.web_enabled:
        app.include_router(dashboard_router)
        app.mount(path="/dashboard/assets", app=StaticFiles(directory=ASSET_DIRECTORY), name="dashboard-assets")
    elif settings.mcp_enabled:
        # MCP 的根挂载会鉴权未知路径；关闭总览时保持整个前缀为 404。
        async def disabled_dashboard(request: Request):
            """阻止已关闭的总览路径落入 MCP 的鉴权入口。

            :returns: 路径不存在的响应。
            """
            return JSONResponse(status_code=404, content={"detail": "Not Found"})

        for path in ("/dashboard", "/dashboard/{path:path}"):
            app.add_route(
                path=path, route=disabled_dashboard,
                methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
            )

    @app.get("/health")
    async def health():
        """返回服务就绪状态。

        :returns: 健康状态。
        """
        return {"status": "ok", "protocol_version": 2}

    @app.exception_handler(ServiceError)
    async def service_error(request: Request, error: ServiceError):
        """返回公开错误码。

        :returns: 不含输入值的错误响应。
        """
        return JSONResponse(status_code=error.status, content={"code": error.code}, headers={"WWW-Authenticate": "Bearer"} if error.status == 401 else None)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request: Request, error: RequestValidationError):
        """防止默认校验错误回显登记秘密。

        :returns: 仅含字段位置与错误类型的响应。
        """
        return JSONResponse(status_code=422, content={"code": "INVALID_REQUEST", "errors": [{"location": list(item["loc"]), "type": item["type"]} for item in error.errors()]})

    if settings.mcp_enabled:
        from runbridge_hub.mcp_server import build_mcp

        mcp, mcp_app = build_mcp(hub=app, settings=settings)
        # SDK 自己拥有 /mcp 路由；挂在末尾，避免重复前缀或覆盖现有 API。
        app.mount(path="/", app=mcp_app)

    app.state.mcp = mcp

    return app
