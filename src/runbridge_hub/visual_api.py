"""画面上传、只读订阅与目标选择接口，不提供展示页面。"""

import asyncio

from fastapi import APIRouter, Header, Request, WebSocket, WebSocketDisconnect
from pydantic import ValidationError

from runbridge_hub.native import reject
from runbridge_hub.security import bearer_token
from runbridge_hub.service import ServiceError
from runbridge_hub.visual_protocol import VisualAuth, VisualHello, VisualIncomingAdapter, VisualSelection, VisualSourceState, VisualTargetRequest, VisualTargets
from runbridge_hub.visual_wire import HEADER_MAX_BYTES, PNG_MAX_BYTES, STATE_MAX_BYTES, unpack_frame


router = APIRouter()


@router.get("/v1/nodes/{node_id}/visual/support")
async def support(node_id: str, request: Request, authorization: str | None = Header(default=None)):
    """节点按当前代次探测独立画面合同。

    :returns: 画面版本和消息限制，不包含页面信息。
    """
    await request.app.state.service.authorize_device(node_id=node_id, token=bearer_token(header=authorization))
    return {"visual_protocol_version": 1, "header_max_bytes": HEADER_MAX_BYTES, "png_max_bytes": PNG_MAX_BYTES}


@router.websocket("/v1/nodes/{node_id}/sessions/{session_id}/visual/upload")
async def upload(websocket: WebSocket, node_id: str, session_id: str):
    """接收已授权的独立上传，错误仅关闭画面通道。"""
    service = websocket.app.state.visual
    channel = None
    try:
        if websocket.query_params:
            raise ServiceError(status=400, code="UNSUPPORTED_VISUAL_QUERY")
        generation = int(websocket.headers.get("x-runbridge-generation", "0"))
        channel = await service.attach(node_id=node_id, session_id=session_id, generation=generation,
                                       token=bearer_token(header=websocket.headers.get("authorization")), websocket=websocket)
    except ValueError:
        await reject(websocket=websocket, error=ServiceError(status=400, code="INVALID_GENERATION"))
        return
    except ServiceError as error:
        await reject(websocket=websocket, error=error)
        return
    try:
        first = await asyncio.wait_for(websocket.receive(), timeout=5)
        raw = first.get("text")
        if raw is None or len(raw.encode()) > STATE_MAX_BYTES:
            raise ValueError("缺少画面握手")
        VisualHello.model_validate_json(raw)
        await service.check_upload(channel=channel, websocket=websocket)
        channel.hello = True
        service.publish(channel=channel)
        while True:
            event = await websocket.receive()
            if event["type"] == "websocket.disconnect":
                break
            await service.check_upload(channel=channel, websocket=websocket)
            if event.get("bytes") is not None:
                data = event["bytes"]
                metadata, _ = unpack_frame(data=data)
                service.frame(channel=channel, metadata=metadata, data=data)
            else:
                raw = event.get("text")
                if raw is None or len(raw.encode()) > STATE_MAX_BYTES:
                    raise ValueError("画面状态消息无效")
                message = VisualIncomingAdapter.validate_json(raw)
                if isinstance(message, VisualTargets):
                    service.targets(channel=channel, values=message.targets)
                elif isinstance(message, VisualSourceState):
                    service.source_state(channel=channel, message=message)
                else:
                    raise ValueError("重复的画面握手")
    except (ValueError, ValidationError, TimeoutError, ServiceError):
        try:
            await websocket.close(code=1008, reason="INVALID_VISUAL_MESSAGE")
        except (RuntimeError, WebSocketDisconnect):
            pass
    except (asyncio.CancelledError, WebSocketDisconnect, RuntimeError, OSError):
        pass
    finally:
        service.detach(channel=channel, websocket=websocket)


@router.put("/v1/sessions/{session_id}/visual/target", response_model=VisualSelection, status_code=202)
async def select_target(session_id: str, body: VisualTargetRequest, request: Request, authorization: str | None = Header(default=None)):
    """核验创建许可再请求切换，202 不表示已经产生新图。"""
    await request.app.state.sessions.query(session_id=session_id, token=bearer_token(header=authorization))
    return await request.app.state.visual.select(session_id=session_id, target_id=body.target_id)


@router.websocket("/v1/sessions/{session_id}/visual/stream")
async def stream(websocket: WebSocket, session_id: str):
    """数据消费者使用独立订阅，不占用执行连接。"""
    service = websocket.app.state.visual
    accepted = False
    channel = None
    queue = None
    tasks = []
    try:
        if websocket.query_params:
            raise ServiceError(status=400, code="UNSUPPORTED_VISUAL_QUERY")
        header = websocket.headers.get("authorization")
        token = bearer_token(header=header)
        if header is None:
            await websocket.accept()
            accepted = True
            first = await asyncio.wait_for(websocket.receive(), timeout=5)
            raw = first.get("text")
            if raw is None or len(raw.encode()) > STATE_MAX_BYTES:
                raise ServiceError(status=401, code="INVALID_ACCESS_TOKEN")
            token = VisualAuth.model_validate_json(raw).access_token.get_secret_value()
        view = await service.sessions.query(session_id=session_id, token=token)
        description = service.describe(view=view)
        if description.stream_path is None:
            raise ServiceError(status=410 if description.state == "STOPPED" else 409, code=description.reason_code or "VISUAL_UNAVAILABLE")
        if not accepted:
            await websocket.accept()
            accepted = True
        channel = service.channel(session=service.sessions.sessions[session_id])
        queue = asyncio.Queue(maxsize=1)
        channel.subscribers[queue] = websocket
        queue.put_nowait((service.snapshot(channel=channel), channel.packet))

        async def send_updates():
            while True:
                value, data = await queue.get()
                if not service.active(session=channel.session):
                    return
                await service.check_lease(session=channel.session)
                async with asyncio.timeout(delay=2):
                    await websocket.send_json({"type": "state", "visual": value.model_dump(mode="json")})
                    if (data is not None and service.active(session=channel.session) and channel.packet is not None
                            and value.stream_id == channel.view.stream_id and value.target_id == channel.view.target_id):
                        await websocket.send_bytes(data=data)

        async def receive_close():
            event = await websocket.receive()
            if event["type"] != "websocket.disconnect":
                raise ValueError("画面订阅保持只读")

        tasks = [asyncio.create_task(coro=send_updates()), asyncio.create_task(coro=receive_close())]
        done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    except ServiceError as error:
        if not accepted:
            await reject(websocket=websocket, error=error)
        else:
            await websocket.close(code=1008, reason=error.code)
    except asyncio.CancelledError:
        pass
    except (ValueError, ValidationError, TimeoutError, WebSocketDisconnect, RuntimeError, OSError):
        if accepted:
            try:
                await websocket.close(code=1008, reason="VISUAL_SUBSCRIPTION_CLOSED")
            except (RuntimeError, WebSocketDisconnect):
                pass
    finally:
        if channel is not None and queue is not None:
            channel.subscribers.pop(queue, None)
        for task in tasks:
            task.cancel()
        try:
            await asyncio.gather(*tasks, return_exceptions=True)
        except asyncio.CancelledError:
            pass
