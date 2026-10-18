"""明确退役官方 SDK 入口；画面接口复用 WebSocket 拒绝响应。"""

from fastapi import APIRouter, WebSocket
from fastapi.responses import JSONResponse

from runbridge_hub.service import ServiceError


router = APIRouter()


async def reject(*, websocket: WebSocket, error: ServiceError):
    if "websocket.http.response" in websocket.scope.get("extensions", {}):
        await websocket.send_denial_response(response=JSONResponse(status_code=error.status, content={"code": error.code}))
    else:
        await websocket.close(code=1008, reason=error.code)


@router.api_route("/v1/nodes/{node_id}/sessions", methods=["POST"])
@router.api_route("/v1/sessions/{session_id}", methods=["GET", "DELETE"])
@router.api_route("/v1/sessions/{session_id}/playwright", methods=["GET"])
@router.api_route("/v1/sessions/{session_id}/cdp", methods=["GET"])
async def retired():
    return JSONResponse(status_code=410, content={"code": "NATIVE_API_RETIRED", "message": "请改用 /v2 的项目工具调用接口或 MCP；不再支持官方 SDK 接入"})


@router.websocket("/v1/sessions/{session_id}/playwright")
@router.websocket("/v1/sessions/{session_id}/cdp")
@router.websocket("/v1/nodes/{node_id}/control")
@router.websocket("/v1/nodes/{node_id}/sessions/{session_id}/tunnel")
async def retired_websocket(websocket: WebSocket):
    await reject(websocket=websocket, error=ServiceError(status=410, code="NATIVE_API_RETIRED"))
