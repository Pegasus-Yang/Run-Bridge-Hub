"""统一项目指令服务：鉴权、排队、去重、关联与有界结果缓存。"""

import asyncio
import json
from collections import OrderedDict
from datetime import UTC, datetime, timedelta
from time import monotonic

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from runbridge_hub.security import bearer_token
from runbridge_hub.service import ServiceError
from runbridge_hub.sessions import TERMINAL
from runbridge_hub.tool_contract import (
    CommandInput,
    Execute,
    MAX_MESSAGE,
    ToolResult,
    fingerprint,
    validate_call,
)


router = APIRouter()
DONE = {"SUCCEEDED", "FAILED", "UNKNOWN"}


class CommandService:
    def __init__(self, *, sessions):
        self.sessions = sessions
        self.store = sessions.nodes.store
        self.pending = {}
        self.tasks = set()
        self.cache = OrderedDict()
        self.cache_bytes = 0
        self.lock = asyncio.Lock()
        self.admissions = set()

    async def start(self):
        await self.store.interrupt_commands()

    def cache_result(self, *, key, value):
        size = len(json.dumps(value).encode())
        if key in self.cache:
            self.cache_bytes -= self.cache.pop(key)[1]
        self.cache[key] = (value, size)
        self.cache_bytes += size
        while (
            self.cache_bytes > 64 * 1024 * 1024
            or sum(item[1] == key[1] for item in self.cache) > 128
        ):
            _, (_, removed) = self.cache.popitem(last=False)
            self.cache_bytes -= removed

    async def query(self, *, session_id, request_id, token):
        view = await self.sessions.query(session_id=session_id, token=token)
        key = (view.grant_id, session_id, request_id)
        row = await self.store.command(key=key)
        if row is None:
            raise ServiceError(status=404, code="REQUEST_NOT_FOUND")
        if key in self.cache:
            return self.cache[key][0]
        return {
            "protocol_version": 2,
            "session_id": session_id,
            "type": "result",
            "connection_generation": view.connection_generation,
            "request_id": request_id,
            "status": row["status"],
            "execution_outcome": row["execution_outcome"],
            "result": None,
            "result_available": False,
            "error": {"code": row["error_code"] or "RESULT_EXPIRED", "retryable": False}
            if row["status"] in DONE
            else None,
        }

    async def submit(self, *, session_id, token, request: CommandInput):
        task = asyncio.create_task(
            self.admit(session_id=session_id, token=token, request=request)
        )
        self.admissions.add(task)
        task.add_done_callback(self.admission_finished)
        return await asyncio.shield(task)

    def admission_finished(self, task):
        self.admissions.discard(task)
        if not task.cancelled():
            task.exception()

    async def admit(self, *, session_id, token, request: CommandInput):
        started = monotonic()
        view = await self.sessions.query(session_id=session_id, token=token)
        try:
            _, params = validate_call(request=request, tool=view.tool)
        except ValueError as error:
            raise ServiceError(
                status=422,
                code=str(error)
                if str(error) in {"METHOD_UNSUPPORTED", "OBJECT_TYPE_MISMATCH"}
                else "INVALID_PARAMS",
            ) from None
        request = request.model_copy(update={"params": params.model_dump(mode="json")})
        key = (view.grant_id, session_id, request.request_id)
        try:
            digest = fingerprint(request=request)
        except ValueError:
            raise ServiceError(status=422, code="INVALID_PARAMS") from None
        async with self.lock:
            old = await self.store.command(key=key)
            if old is not None:
                if old["digest"] != digest:
                    raise ServiceError(status=409, code="REQUEST_ID_CONFLICT")
                future = self.pending.get(key)
            else:
                session = self.sessions.sessions.get(session_id)
                if (
                    session is None
                    or view.state not in {"READY", "ACTIVE"}
                    or view.expires_at <= datetime.now(UTC)
                ):
                    raise ServiceError(status=409, code="SESSION_NOT_ACTIVE")
                if sum(item[1] == session_id for item in self.pending) >= 17:
                    raise ServiceError(status=409, code="RESOURCE_BUSY")
                resource = next(
                    (
                        item
                        for item in session.connection.capabilities.resources
                        if item.resource_id == view.resource_id
                    ),
                    None,
                )
                if resource is None or request.method not in resource.methods:
                    raise ServiceError(status=409, code="METHOD_UNSUPPORTED")
                row, created = await self.store.begin_command(
                    key=key, digest=digest, method=request.method
                )
                if row is None:
                    raise ServiceError(status=429, code="REQUEST_LIMIT")
                future = asyncio.get_running_loop().create_future()
                self.pending[key] = future
                task = asyncio.create_task(
                    self.dispatch(
                        session=session,
                        token=token,
                        request=request,
                        params=params,
                        key=key,
                        started=started,
                    )
                )
                self.tasks.add(task)
                task.add_done_callback(self.tasks.discard)
        if future is not None:
            try:
                await asyncio.wait_for(
                    asyncio.shield(future),
                    timeout=max(
                        0.001, params.timeout / 1000 + 0.5 - (monotonic() - started)
                    ),
                )
            except TimeoutError:
                pass
        return await self.query(
            session_id=session_id, request_id=request.request_id, token=token
        )

    async def dispatch(self, *, session, token, request, params, key, started):
        try:
            async with session.command_lock:
                if self.pending.get(key) is None:
                    return
                view = await self.sessions.query(
                    session_id=session.view.session_id, token=token
                )
                remaining = min(
                    params.timeout - int((monotonic() - started) * 1000),
                    int((view.expires_at - datetime.now(UTC)).total_seconds() * 1000),
                )
                if remaining <= 0:
                    await self.finish(
                        key=key,
                        value=self.failure(
                            request_id=request.request_id,
                            session_id=view.session_id,
                            generation=view.connection_generation,
                            code="ACTION_TIMEOUT",
                            outcome="NOT_STARTED",
                        ),
                    )
                    return
                if session.view.state not in {"READY", "ACTIVE"}:
                    raise ServiceError(status=409, code="SESSION_NOT_ACTIVE")
                envelope = Execute(
                    **request.model_dump(),
                    session_id=view.session_id,
                    connection_generation=view.connection_generation,
                    tool=view.tool,
                    tool_api_version=view.tool_api_version,
                    remaining_ms=remaining,
                )
                async with self.sessions.nodes.lock:
                    await self.sessions.nodes.resolve_access(token=token)
                    if key not in self.pending or session.view.state not in {"READY", "ACTIVE"}:
                        raise ServiceError(status=409, code="SESSION_NOT_ACTIVE")
                    session.view.state = "ACTIVE"
                    session.view.execution_outcome = "NOT_TRACKED"
                    await self.sessions.save(view=session.view)
                    await self.store.finish_command(key=key, status="DISPATCHED")
                    await self.sessions.nodes.leases.activity_started(
                        grant_id=key[0], key=key,
                        deadline=datetime.now(UTC) + timedelta(milliseconds=remaining + 500),
                    )
                    await session.send(value=envelope.model_dump(mode="json"))
                future = self.pending.get(key)
                if future is not None:
                    await asyncio.wait_for(asyncio.shield(future), timeout=remaining / 1000 + 0.5)
        except ServiceError as error:
            await self.finish(
                key=key,
                value=self.failure(
                    request_id=request.request_id,
                    session_id=session.view.session_id,
                    generation=session.view.connection_generation,
                    code=error.code,
                    outcome="NOT_STARTED",
                ),
            )
        except OSError, RuntimeError, WebSocketDisconnect, TimeoutError:
            await self.finish(
                key=key,
                value=self.failure(
                    request_id=request.request_id,
                    session_id=session.view.session_id,
                    generation=session.view.connection_generation,
                    code="RESULT_UNKNOWN",
                    outcome="OUTCOME_UNKNOWN",
                    status="UNKNOWN",
                ),
            )
            await self.sessions.close(session=session, reason="COMMAND_OUTCOME_UNKNOWN", terminal_state="INTERRUPTED")

    @staticmethod
    def failure(*, request_id, session_id, generation, code, outcome, status="FAILED"):
        return {
            "protocol_version": 2,
            "request_id": request_id,
            "session_id": session_id,
            "type": "result",
            "connection_generation": generation,
            "status": status,
            "execution_outcome": outcome,
            "result": None,
            "error": {
                "code": code,
                "message": "请求未完成，请查询状态并核对实际结果",
                "retryable": False,
            },
        }

    async def finish(self, *, key, value):
        future = self.pending.get(key)
        if future is None:
            return
        await self.store.finish_command(
            key=key,
            status=value["status"],
            outcome=value["execution_outcome"],
            code=value.get("error", {}).get("code") if value.get("error") else None,
        )
        self.cache_result(key=key, value=value)
        self.pending.pop(key, None)
        await self.sessions.nodes.leases.activity_finished(grant_id=key[0], key=key, success=value["status"] != "UNKNOWN")
        if not future.done():
            future.set_result(value)

    async def receive(self, *, session, value):
        if (
            value.get("protocol_version") != 2
            or value.get("session_id") != session.view.session_id
            or value.get("connection_generation") != session.view.connection_generation
        ):
            raise ValueError("INVALID_EXECUTION_MESSAGE")
        if value.get("type") == "session_ready":
            if (
                session.view.state != "PREPARING"
                or value.get("runtime_version") != session.view.runtime_version
                or not isinstance(value.get("objects"), dict)
            ):
                raise ValueError("INVALID_SESSION_PREPARATION")
            session.view.objects = value["objects"]
            await self.sessions.save(view=session.view)
            await session.send(
                value={
                    "protocol_version": 2,
                    "type": "session_ready_ack",
                    "session_id": session.view.session_id,
                    "connection_generation": session.view.connection_generation,
                }
            )
            return
        if value.get("type") == "event":
            sequence = value.get("event_seq")
            if not isinstance(sequence, int) or sequence <= session.event_seq:
                return
            session.event_seq = sequence
            objects = value.get("data", {}).get("objects")
            if isinstance(objects, dict) and session.view.state in {"READY", "ACTIVE"}:
                session.view.objects = objects
                await self.sessions.save(view=session.view)
            return
        request_id = value.get("request_id")
        key = (session.view.grant_id, session.view.session_id, request_id)
        if key not in self.pending:
            return
        if value.get("type") == "result":
            result = ToolResult.model_validate(value)
            await self.finish(key=key, value=result.model_dump(mode="json"))
        elif value.get("type") in {"command_ack", "command_started"}:
            await self.store.finish_command(
                key=key,
                status="RUNNING" if value["type"] == "command_started" else "ACCEPTED",
            )
        else:
            raise ValueError("INVALID_EXECUTION_MESSAGE")

    async def closed(self, *, session_id, reason):
        record = await self.store.session(session_id=session_id)
        for key in list(self.pending):
            if key[1] == session_id:
                await self.finish(
                    key=key,
                    value=self.failure(
                        request_id=key[2],
                        session_id=session_id,
                        generation=record["connection_generation"],
                        code="RESULT_UNKNOWN",
                        outcome="OUTCOME_UNKNOWN",
                        status="UNKNOWN",
                    ),
                )

    async def shutdown(self):
        for key in list(self.pending):
            await self.closed(session_id=key[1], reason="HUB_RESTARTED")
        await asyncio.gather(*list(self.tasks), return_exceptions=True)
        await asyncio.gather(*list(self.admissions), return_exceptions=True)


@router.websocket("/v2/nodes/{node_id}/sessions/{session_id}/execution")
async def execution(websocket: WebSocket, node_id: str, session_id: str):
    service = websocket.app.state.sessions
    session = None
    try:
        session = await service.attach_execution(
            node_id=node_id,
            session_id=session_id,
            generation=int(websocket.headers.get("x-runbridge-generation", "0")),
            token=bearer_token(header=websocket.headers.get("authorization")),
            websocket=websocket,
        )
        while True:
            event = await websocket.receive()
            if event["type"] == "websocket.disconnect":
                break
            raw = event.get("text")
            if raw is None or len(raw.encode()) > MAX_MESSAGE:
                raise ValueError("INVALID_EXECUTION_MESSAGE")
            await websocket.app.state.commands.receive(
                session=session, value=json.loads(raw)
            )
    except ServiceError, ValueError, WebSocketDisconnect, RuntimeError:
        pass
    finally:
        if (
            session is not None
            and session.view.state not in TERMINAL
            and session.view.state != "CLOSING"
        ):
            await service.close(
                session=session,
                reason="EXECUTION_DISCONNECTED",
                terminal_state="INTERRUPTED",
            )
