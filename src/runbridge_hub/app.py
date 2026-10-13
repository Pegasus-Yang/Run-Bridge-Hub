"""单实例 Hub 的 ASGI 应用工厂。"""

import asyncio
from contextlib import AsyncExitStack, asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from runbridge_hub import __version__

from runbridge_hub.api import router as management_router
from runbridge_hub.gateway import router as gateway_router
from runbridge_hub.service import NodeService, ServiceError
from runbridge_hub.sessions import SessionService
from runbridge_hub.native import router as native_router
from runbridge_hub.settings import HubSettings
from runbridge_hub.store import Store
from runbridge_hub.visual import VisualService
from runbridge_hub.visual_api import router as visual_router


def create_app(*, settings: HubSettings) -> FastAPI:
    """创建具有独立内存状态的单 Worker 应用。

    :param settings: 运行配置。
    :returns: ASGI 应用。
    """
    mcp = None

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        store = Store(path=settings.database_path)
        await store.open()
        service = NodeService(store=store, settings=settings)
        app.state.service = service
        sessions = SessionService(nodes=service)
        app.state.sessions = sessions
        visual = VisualService(sessions=sessions)
        app.state.visual = visual
        sessions.on_close = visual.close
        service.on_disconnect = sessions.interrupt_node
        await sessions.start()
        await visual.start()
        browsers = None
        try:
            async with AsyncExitStack() as stack:
                if mcp is not None:
                    from runbridge_hub.browser import BrowserService

                    browsers = BrowserService(sessions=sessions, native_url=settings.mcp_native_url, visual=visual)
                    app.state.browsers = browsers

                    async def close_extensions(*, session_id: str, reason: str) -> None:
                        """同一次关闭同时释放画面订阅和 MCP 对象。"""
                        await asyncio.gather(visual.close(session_id=session_id, reason=reason), browsers.discard(session_id=session_id, reason=reason))

                    sessions.on_close = close_extensions
                    await browsers.start()
                    await stack.enter_async_context(mcp.session_manager.run())
                yield
        finally:
            if browsers is not None:
                await browsers.shutdown()
            await sessions.shutdown()
            await visual.shutdown()
            await service.close()
            await store.close()

    app = FastAPI(title="RunBridge Hub", version=__version__, lifespan=lifespan)
    app.include_router(management_router)
    app.include_router(gateway_router)
    app.include_router(native_router)
    app.include_router(visual_router)

    @app.get("/health")
    async def health():
        """返回服务就绪状态。

        :returns: 健康状态。
        """
        return {"status": "ok", "protocol_version": 1}

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

    return app
