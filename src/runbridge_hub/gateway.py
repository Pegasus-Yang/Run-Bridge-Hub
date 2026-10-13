"""节点控制连接，与原生执行隧道分别传输。"""

import asyncio

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from runbridge_hub.protocol import ControlError, IncomingAdapter, Welcome, SessionPrepared, SessionClosed, SessionAcknowledgement
from runbridge_hub.security import bearer_token
from runbridge_hub.service import ServiceError


router = APIRouter()
CONTROL_MAX_BYTES = 65_536


@router.websocket("/v1/nodes/{node_id}/control")
async def control(websocket: WebSocket, node_id: str):
    """验证节点身份，接收能力与心跳。

    :param websocket: 控制连接。
    :param node_id: 目标节点。
    """
    service = websocket.app.state.service
    try:
        await service.authorize_owner(node_id=node_id, token=bearer_token(header=websocket.headers.get("authorization")))
    except ServiceError:
        await websocket.close(code=1008)
        return
    await websocket.accept()
    connection = None
    try:
        connection = await service.attach(node_id=node_id, websocket=websocket)
        welcome = Welcome(node_id=node_id, connection_generation=connection.generation, heartbeat_interval_seconds=service.settings.heartbeat_interval_seconds, heartbeat_timeout_seconds=service.settings.heartbeat_timeout_seconds)
        await connection.send(message=welcome)
        while True:
            event = await asyncio.wait_for(websocket.receive(), timeout=service.settings.heartbeat_timeout_seconds)
            if event["type"] == "websocket.disconnect":
                break
            raw = event.get("text")
            if raw is None or len(raw.encode()) > CONTROL_MAX_BYTES:
                raise ServiceError(status=400, code="INVALID_CONTROL_MESSAGE")
            try:
                message = IncomingAdapter.validate_json(raw)
            except ValidationError:
                raise ServiceError(status=400, code="INVALID_CONTROL_MESSAGE") from None
            if isinstance(message, (SessionPrepared, SessionClosed)):
                await websocket.app.state.sessions.report(connection=connection, message=message)
                acknowledgement = SessionAcknowledgement(connection_generation=connection.generation, session_id=message.session_id)
            else:
                acknowledgement = await service.receive(connection=connection, message=message)
            await connection.send(message=acknowledgement)
    except TimeoutError:
        try:
            await websocket.close(code=1001, reason="heartbeat_timeout")
        except (WebSocketDisconnect, RuntimeError):
            pass
    except ServiceError as error:
        try:
            await websocket.send_json(ControlError(code=error.code).model_dump(mode="json"))
            await websocket.close(code=1008, reason=error.code)
        except (WebSocketDisconnect, RuntimeError):
            pass
    except WebSocketDisconnect:
        pass
    finally:
        if connection is not None:
            await service.detach(connection=connection)
