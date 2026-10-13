"""转发原生文本和二进制消息，不解析或重放工具调用。"""

import asyncio
from datetime import UTC, datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse

from runbridge_hub.security import bearer_token
from runbridge_hub.service import ServiceError
from runbridge_hub.sessions import NATIVE_MAX_BYTES


router = APIRouter()


async def reject(*, websocket: WebSocket, error: ServiceError) -> None:
    """以握手 HTTP 状态返回管理错误。

    :param websocket: 尚未接受的连接。
    :param error: 公开错误。
    """
    if "websocket.http.response" in websocket.scope.get("extensions", {}):
        await websocket.send_denial_response(response=JSONResponse(status_code=error.status, content={"code": error.code}))
    else:
        await websocket.close(code=1008)


async def forward(*, source: WebSocket, target: WebSocket, session) -> int:
    """逐消息等待下游发送，保持类型与顺序并传递背压。

    :param source: 原生入口。
    :param target: 原生出口。
    """
    while True:
        event = await source.receive()
        if event["type"] == "websocket.disconnect":
            return event.get("code", 1006)
        if session.view.state != "ACTIVE":
            raise ServiceError(status=409, code="SESSION_CLOSING")
        if session.view.expires_at <= datetime.now(UTC):
            raise ServiceError(status=409, code="SESSION_EXPIRED")
        text = event.get("text")
        data = event.get("bytes")
        if text is not None:
            if len(text.encode()) > NATIVE_MAX_BYTES:
                raise ServiceError(status=413, code="NATIVE_MESSAGE_TOO_LARGE")
            await target.send_text(data=text)
        elif data is not None:
            if len(data) > NATIVE_MAX_BYTES:
                raise ServiceError(status=413, code="NATIVE_MESSAGE_TOO_LARGE")
            await target.send_bytes(data=data)


@router.websocket("/v1/nodes/{node_id}/sessions/{session_id}/tunnel")
async def tunnel(websocket: WebSocket, node_id: str, session_id: str):
    """节点主动建立每会话独立的出站隧道。

    :param websocket: 节点原生隧道。
    :param node_id: 节点 ID。
    :param session_id: 当前会话。
    """
    service = websocket.app.state.sessions
    try:
        generation = int(websocket.headers.get("x-runbridge-generation", "0"))
        session = await service.attach_tunnel(node_id=node_id, session_id=session_id, generation=generation, token=bearer_token(header=websocket.headers.get("authorization")), websocket=websocket)
    except ValueError:
        await reject(websocket=websocket, error=ServiceError(status=400, code="INVALID_GENERATION"))
        return
    except ServiceError as error:
        await reject(websocket=websocket, error=error)
        return
    tasks = [asyncio.create_task(session.caller_attached.wait()), asyncio.create_task(session.finished.wait()), asyncio.create_task(websocket.receive())]
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        if tasks[2] in done and not session.caller_attached.is_set():
            await service.close(session=session, reason="NODE_TUNNEL_CLOSED", terminal_state="INTERRUPTED")
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        session.reader_released.set()
        await session.finished.wait()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        session.reader_released.set()
        await service.close(session=session, reason="NODE_TUNNEL_CLOSED", terminal_state="INTERRUPTED")


@router.websocket("/v1/sessions/{session_id}/playwright")
async def playwright(websocket: WebSocket, session_id: str):
    """允许官方 SDK 使用原生对象、事件、错误和文件传输。

    :param websocket: 调用方原生连接。
    :param session_id: 受保护会话。
    """
    await execute(websocket=websocket, session_id=session_id, native_protocol="playwright")


@router.websocket("/v1/sessions/{session_id}/cdp")
async def cdp(websocket: WebSocket, session_id: str):
    """接入已有 Chrome 的官方 connect_over_cdp 客户端。

    :param websocket: 调用方连接。
    :param session_id: 受保护会话。
    """
    await execute(websocket=websocket, session_id=session_id, native_protocol="cdp")


async def execute(*, websocket: WebSocket, session_id: str, native_protocol: str) -> None:
    """两种原生协议共用授权、路由和断开清理。

    :param websocket: 调用方连接。
    :param session_id: 管理会话。
    :param native_protocol: 当前入口对应的协议。
    """
    service = websocket.app.state.sessions
    try:
        session = await service.attach_caller(session_id=session_id, token=bearer_token(header=websocket.headers.get("authorization")), websocket=websocket, native_protocol=native_protocol)
    except ServiceError as error:
        await reject(websocket=websocket, error=error)
        return
    tasks = [asyncio.create_task(forward(source=websocket, target=session.tunnel, session=session)), asyncio.create_task(forward(source=session.tunnel, target=websocket, session=session))]
    restarting = False
    reason = "EXECUTION_CONNECTION_CLOSED"
    try:
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            if task.result() == 1012:
                restarting = True
    except ServiceError as error:
        reason = error.code
    except (WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await service.close(session=session, reason="HUB_RESTARTED" if restarting else reason, terminal_state="INTERRUPTED" if restarting else "CLOSED")
