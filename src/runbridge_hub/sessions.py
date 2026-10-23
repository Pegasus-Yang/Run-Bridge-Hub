"""工具资源独占、会话、租期与节点确认清理。"""

import asyncio
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import WebSocket, WebSocketDisconnect

from runbridge_hub.protocol import (
    SessionClosed,
    SessionCreate,
    SessionOpen,
    SessionPrepared,
    SessionStop,
    SessionView,
)
from runbridge_hub.service import Connection, NodeService, ServiceError


TERMINAL = {"CLOSED", "FAILED", "INTERRUPTED"}


async def close_websocket(*, websocket: WebSocket | None, reason: str):
    if websocket is not None:
        try:
            await asyncio.wait_for(websocket.close(code=1000, reason=reason), timeout=3)
        except WebSocketDisconnect, RuntimeError, OSError, TimeoutError:
            pass


@dataclass
class Session:
    view: SessionView
    connection: Connection
    prepared: asyncio.Event = field(default_factory=asyncio.Event)
    finished: asyncio.Event = field(default_factory=asyncio.Event)
    cleaned: asyncio.Event = field(default_factory=asyncio.Event)
    execution: WebSocket | None = None
    send_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    command_lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    terminal_state: str = "CLOSED"
    event_seq: int = 0

    async def send(self, *, value: dict):
        async with self.send_lock:
            if self.execution is None:
                raise ServiceError(status=409, code="SESSION_NOT_ACTIVE")
            await asyncio.wait_for(self.execution.send_json(value), timeout=5)


class SessionService:
    def __init__(self, *, nodes: NodeService):
        self.nodes = nodes
        self.sessions = {}
        self.maintenance_task = None
        self.on_close = None
        self.open_tasks = {}
        self.admissions = set()

    async def start(self):
        await self.nodes.store.interrupt_mcp_requests()
        for record in await self.nodes.store.unfinished_sessions():
            record.update(
                state="INTERRUPTED",
                cleanup="UNKNOWN",
                close_reason="HUB_RESTARTED",
                updated_at=datetime.now(UTC).isoformat(),
            )
            if record.get("protocol_version", 1) == 1:
                record["native_path"] = None
            # 保留历史协议与字段，不能把旧原生记录改写成 v2 执行证据。
            await self.nodes.store.save_session(
                session_id=record["session_id"],
                node_id=record["node_id"],
                grant_id=record["grant_id"],
                record=json.dumps(record),
            )
        self.maintenance_task = asyncio.create_task(self.maintenance())

    async def save(self, *, view: SessionView, request_id: str | None = None):
        await self.nodes.store.save_session(
            session_id=view.session_id,
            node_id=view.node_id,
            grant_id=view.grant_id,
            record=view.model_dump_json(),
            mcp_request_id=request_id,
        )

    async def create(
        self, *, node_id: str, token: str | None, request: SessionCreate
    ) -> SessionView:
        # 受理及分配属于服务生命周期，调用方断线不能留下无人处理的 PENDING 记录。
        task = asyncio.create_task(
            self.admit(node_id=node_id, token=token, request=request)
        )
        self.admissions.add(task)
        task.add_done_callback(self.admission_finished)
        return await asyncio.shield(task)

    def admission_finished(self, task):
        self.admissions.discard(task)
        if not task.cancelled():
            task.exception()

    async def admit(
        self, *, node_id: str, token: str | None, request: SessionCreate
    ) -> SessionView:
        grant = await self.nodes.authorize_access(node_id=node_id, token=token)
        request_id = request.request_id or f"open_{uuid4().hex}"
        key = (grant["grant_id"], node_id, request_id)
        arguments = request.model_dump(exclude={"request_id"})
        record, created = await self.nodes.store.begin_mcp_request(
            key=key, arguments=arguments
        )
        if record is None:
            raise ServiceError(status=429, code="REQUEST_LIMIT")
        if json.loads(record["arguments"]) != arguments:
            raise ServiceError(status=409, code="REQUEST_ID_CONFLICT")
        if not created:
            if key in self.open_tasks:
                return await asyncio.shield(self.open_tasks[key])
            if record["state"] == "SUCCEEDED" and record["session_id"]:
                return await self.query(session_id=record["session_id"], token=token)
            raise ServiceError(
                status=409, code=record["error_code"] or "REQUEST_OUTCOME_UNKNOWN"
            )

        async def prepare():
            try:
                view = await self.allocate(
                    node_id=node_id, token=token, request=request, request_id=request_id
                )
                await self.nodes.store.finish_mcp_request(
                    key=key,
                    state="SUCCEEDED",
                    page_id=view.objects.get("default_page_id"),
                )
                return view
            except ServiceError as error:
                await self.nodes.store.finish_mcp_request(
                    key=key, state="FAILED", error_code=error.code
                )
                raise
            except BaseException:
                await self.nodes.store.finish_mcp_request(
                    key=key, state="UNKNOWN", error_code="REQUEST_OUTCOME_UNKNOWN"
                )
                raise
            finally:
                self.open_tasks.pop(key, None)

        task = asyncio.create_task(prepare())
        self.open_tasks[key] = task
        return await asyncio.shield(task)

    async def allocate(self, *, node_id, token, request, request_id):
        async with self.nodes.lock:
            grant = await self.nodes.authorize_access(node_id=node_id, token=token)
            live = self.nodes.connections.get(node_id)
            now = datetime.now(UTC)
            if (
                live is None
                or live.capabilities is None
                or (now - live.last_seen_at).total_seconds()
                >= self.nodes.settings.heartbeat_timeout_seconds
            ):
                raise ServiceError(status=409, code="NODE_OFFLINE")
            resource = next(
                (
                    item
                    for item in live.capabilities.resources
                    if item.resource_id == request.resource_id
                ),
                None,
            )
            if resource is None or resource.tool != request.tool:
                raise ServiceError(status=404, code="RESOURCE_NOT_FOUND")
            if resource.tool_api_version != 1 or not resource.methods:
                raise ServiceError(status=428, code="TOOL_API_UNSUPPORTED")
            if resource.readiness != "READY":
                raise ServiceError(status=409, code="RESOURCE_NOT_READY")
            if (
                resource.kind == "BORROWED_CHROME_CDP"
                and resource.authorization_scope != "BROWSER_INSTANCE"
            ):
                raise ServiceError(status=409, code="RESOURCE_NOT_AUTHORIZED")
            if (
                node_id,
                request.resource_id,
            ) in self.nodes.reservations or resource.occupancy != "FREE":
                raise ServiceError(status=409, code="RESOURCE_BUSY")
            backend = next(
                (
                    item
                    for item in live.capabilities.backends
                    if item.name == resource.backend
                ),
                None,
            )
            if (
                backend is None
                or backend.runtime_version is None
                or backend.coverage_status != "SUPPORTED"
            ):
                raise ServiceError(status=409, code="BACKEND_UNAVAILABLE")
            expires = now + timedelta(seconds=request.lease_seconds)
            if grant["expires_at"]:
                expires = min(expires, datetime.fromisoformat(grant["expires_at"]))
            view = SessionView(
                session_id=f"session_{uuid4().hex}",
                node_id=node_id,
                resource_id=request.resource_id,
                grant_id=grant["grant_id"],
                connection_generation=live.generation,
                backend=resource.backend,
                runtime_version=backend.runtime_version,
                tool=request.tool,
                tool_api_version=resource.tool_api_version,
                request_id=request_id,
                authorization_scope=resource.authorization_scope,
                state="PREPARING",
                created_at=now,
                updated_at=now,
                expires_at=expires,
            )
            session = Session(view=view, connection=live)
            await self.save(view=view, request_id=request_id)
            self.sessions[view.session_id] = session
            self.nodes.reservations[(node_id, request.resource_id)] = view.session_id
            await self.nodes.leases.activity_started(grant_id=view.grant_id, key=view.session_id, deadline=min(view.expires_at, now + timedelta(seconds=35)))
        try:
            await live.send(
                message=SessionOpen(
                    connection_generation=live.generation,
                    session_id=view.session_id,
                    resource_id=view.resource_id,
                    tool=view.tool,
                    tool_api_version=view.tool_api_version,
                )
            )
            await asyncio.wait_for(session.prepared.wait(), timeout=30)
        except OSError, RuntimeError, WebSocketDisconnect, TimeoutError:
            await self.close(
                session=session, reason="PREPARE_TIMEOUT", terminal_state="FAILED"
            )
            raise ServiceError(status=504, code="SESSION_PREPARE_FAILED") from None
        if session.view.state != "READY":
            raise ServiceError(
                status=409, code=session.view.error_code or "SESSION_PREPARE_FAILED"
            )
        return view.model_copy(deep=True)

    async def query(self, *, session_id: str, token: str | None) -> SessionView:
        record = await self.nodes.store.session(session_id=session_id)
        if record is None:
            raise ServiceError(status=404, code="SESSION_NOT_FOUND")
        view = SessionView.from_record(record=record)
        grant = await self.nodes.authorize_access(node_id=view.node_id, token=token)
        if view.grant_id != grant["grant_id"]:
            raise ServiceError(status=403, code="SESSION_OUTSIDE_GRANT")
        return view

    async def report(self, *, connection: Connection, message):
        async with self.nodes.lock:
            session = self.sessions.get(message.session_id)
            if (
                session is None
                or session.connection is not connection
                or self.nodes.connections.get(connection.node_id) is not connection
                or message.connection_generation != connection.generation
            ):
                raise ServiceError(status=409, code="STALE_SESSION")
            view = session.view
            was_cleaned = view.cleanup == "COMPLETE"
            if isinstance(message, SessionPrepared):
                if view.state != "PREPARING":
                    return
                if message.error_code:
                    view.error_code = message.error_code
                    view.state = "CLOSING"
                    session.terminal_state = "FAILED"
                elif (
                    session.execution is None
                    or message.runtime_version != view.runtime_version
                ):
                    raise ServiceError(status=409, code="INVALID_SESSION_PREPARATION")
                else:
                    view.objects = message.objects or view.objects
                    view.state = "READY"
                await self.nodes.leases.activity_finished(grant_id=view.grant_id, key=view.session_id, success=view.state == "READY")
            else:
                await self.nodes.leases.activity_finished(grant_id=view.grant_id, key=view.session_id, success=False)
                await self.nodes.leases.activity_finished(grant_id=view.grant_id, key=("cleanup", view.session_id), success=message.cleanup == "COMPLETE")
                view.state = session.terminal_state
                view.cleanup = message.cleanup
                view.close_reason = view.close_reason or "TOOL_CLOSED"
                if message.error_code:
                    view.error_code = message.error_code
                    view.state = (
                        "INTERRUPTED"
                        if session.terminal_state != "FAILED"
                        else "FAILED"
                    )
                if message.cleanup == "COMPLETE":
                    self.nodes.reservations.pop((view.node_id, view.resource_id), None)
            view.updated_at = datetime.now(UTC)
            await self.save(view=view)
            # 调用方醒来即可查询 READY；不能先通知，再等待租约和会话落库。
            session.prepared.set()
            if isinstance(message, SessionClosed):
                session.finished.set()
                session.cleaned.set()
            if isinstance(message, SessionClosed) and view.state == "CLOSED" and message.cleanup == "COMPLETE" and not was_cleaned:
                await self.nodes.leases.cleaned(grant_id=view.grant_id)
        if isinstance(message, SessionClosed):
            if self.on_close:
                await self.on_close(
                    session_id=view.session_id, reason=view.close_reason
                )
            await close_websocket(websocket=session.execution, reason=view.close_reason)

    async def attach_execution(
        self, *, node_id, session_id, generation, token, websocket
    ):
        await self.nodes.authorize_device(node_id=node_id, token=token)
        async with self.nodes.lock:
            session = self.sessions.get(session_id)
            if (
                session is None
                or session.view.node_id != node_id
                or session.connection is not self.nodes.connections.get(node_id)
                or session.view.connection_generation != generation
                or session.view.state != "PREPARING"
                or session.execution is not None
            ):
                raise ServiceError(status=409, code="INVALID_SESSION_EXECUTION")
            grant = await self.nodes.store.grant(grant_id=session.view.grant_id)
            if grant["state"] != "HELD" or await self.nodes.leases.invalid_reason(record=grant):
                raise ServiceError(status=409, code="INVALID_SESSION_EXECUTION")
            await websocket.accept()
            session.execution = websocket
            return session

    async def close(
        self, *, session: Session, reason: str, terminal_state: str = "CLOSED"
    ):
        async with self.nodes.lock:
            if session.view.state in TERMINAL or session.view.state == "CLOSING":
                return
            session.terminal_state = terminal_state
            session.view.state = "CLOSING"
            session.view.close_reason = reason
            session.view.updated_at = datetime.now(UTC)
            await self.nodes.leases.activity_finished(grant_id=session.view.grant_id, key=session.view.session_id, success=False)
            if reason == "SESSION_RELEASED":
                grant = await self.nodes.store.grant(grant_id=session.view.grant_id)
                if grant["state"] == "HELD":
                    await self.nodes.leases.activity_started(grant_id=session.view.grant_id, key=("cleanup", session.view.session_id),
                                                             deadline=min(session.view.expires_at, datetime.now(UTC) + timedelta(seconds=10)), refresh=False)
            await self.save(view=session.view)
            session.prepared.set()
            session.finished.set()
            stop = asyncio.create_task(
                session.connection.send(
                    message=SessionStop(
                        connection_generation=session.view.connection_generation,
                        session_id=session.view.session_id,
                        reason=reason,
                    )
                )
            )
        if self.on_close:
            await self.on_close(session_id=session.view.session_id, reason=reason)
        try:
            await stop
        except RuntimeError, OSError, WebSocketDisconnect, TimeoutError:
            pass

    async def release(self, *, session_id, token):
        view = await self.query(session_id=session_id, token=token)
        session = self.sessions.get(session_id)
        if session and view.state not in TERMINAL:
            await self.close(session=session, reason="SESSION_RELEASED")
            try:
                await asyncio.wait_for(session.cleaned.wait(), timeout=10)
            except TimeoutError:
                pass
            return session.view.model_copy(deep=True)
        return view

    async def interrupt_node(self, *, node_id, generation):
        for session in list(self.sessions.values()):
            if (
                session.view.node_id == node_id
                and session.view.connection_generation == generation
                and session.view.state not in TERMINAL
            ):
                await self.close(
                    session=session,
                    reason="NODE_DISCONNECTED",
                    terminal_state="INTERRUPTED",
                )
                session.view.state = "INTERRUPTED"
                session.view.cleanup = "UNKNOWN"
                session.cleaned.set()
                await self.save(view=session.view)

    async def maintenance(self):
        while True:
            await asyncio.sleep(0.25)
            now = datetime.now(UTC)
            for session in list(self.sessions.values()):
                if session.view.state in TERMINAL:
                    if (
                        session.view.cleanup == "COMPLETE"
                        or self.nodes.connections.get(session.view.node_id)
                        is not session.connection
                    ):
                        self.sessions.pop(session.view.session_id, None)
                elif session.view.state == "CLOSING":
                    if (now - session.view.updated_at).total_seconds() >= 10:
                        session.view.state = session.terminal_state
                        session.view.cleanup = "UNKNOWN"
                        session.cleaned.set()
                        await self.save(view=session.view)
                elif session.view.expires_at <= now:
                    await self.close(session=session, reason="SESSION_EXPIRED")

    async def shutdown(self):
        if self.maintenance_task:
            self.maintenance_task.cancel()
            await asyncio.gather(self.maintenance_task, return_exceptions=True)
        for session in list(self.sessions.values()):
            await self.close(
                session=session, reason="HUB_RESTARTED", terminal_state="INTERRUPTED"
            )
        for task in list(self.admissions):
            try:
                await asyncio.wait_for(asyncio.shield(task), timeout=6)
            except ServiceError, TimeoutError:
                pass
