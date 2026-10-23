"""匿名 Node 使用权：领取、活动、续租及经清理确认的交接。"""

import asyncio
import hashlib
import json
import secrets
import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from runbridge_hub.protocol import GrantCreated, GrantRequest, GrantView
from runbridge_hub.security import matches, token_hash
from runbridge_hub.service import ServiceError
from runbridge_hub.sessions import TERMINAL


class LeaseService:
    """与会话分配共用节点锁，等待设备清理时释放锁。"""

    def __init__(self, *, nodes, sessions):
        self.nodes = nodes
        self.sessions = sessions
        self.store = nodes.store
        self.settings = nodes.settings
        self.activities = {}
        self.reclaims = {}
        self.task = None
        self.hub_digest = token_hash(token=self.settings.hub_token.get_secret_value()) if self.settings.hub_token else None

    def authorize_hub(self, *, token):
        """Hub 凭据仅供资源池及新申请使用。"""
        if self.hub_digest is None:
            raise ServiceError(status=503, code="HUB_ACCESS_NOT_CONFIGURED")
        if token is None or not matches(token=token, expected_hash=self.hub_digest):
            raise ServiceError(status=401, code="INVALID_HUB_TOKEN")

    def duration(self, *, seconds):
        value = min(3600, self.settings.grant_max_lease_seconds) if seconds is None else seconds
        if value > self.settings.grant_max_lease_seconds:
            raise ServiceError(status=422, code="LEASE_TOO_LONG")
        return value

    def inflight(self, *, grant_id, now):
        return any(deadline > now for deadline in self.activities.get(grant_id, {}).values())

    def due(self, *, record, now):
        if datetime.fromisoformat(record["expires_at"]) <= now:
            return "LEASE_EXPIRED"
        if not self.inflight(grant_id=record["grant_id"], now=now) and now >= datetime.fromisoformat(record["last_activity_at"]) + timedelta(seconds=record["idle_timeout_seconds"]):
            return "IDLE_TIMEOUT"
        return None

    async def holder(self, *, grant_id, token):
        """匹配原令牌，不要求原租约仍可执行。"""
        record = await self.store.grant_by_token(token_digest=token_hash(token=token)) if token is not None else None
        if record is None:
            raise ServiceError(status=401, code="INVALID_ACCESS_TOKEN")
        if record["grant_id"] != grant_id:
            raise ServiceError(status=403, code="GRANT_OUTSIDE_TOKEN")
        return record

    async def resolve(self, *, token):
        """每次执行检查期限，不能依赖维护循环已经运行。"""
        record = await self.store.grant_by_token(token_digest=token_hash(token=token)) if token is not None else None
        if record is not None and record["state"] == "HELD":
            reason = await self.invalid_reason(record=record)
            if reason is None:
                return record
            self.schedule(grant_id=record["grant_id"], reason=reason)
        raise ServiceError(status=401, code="INVALID_ACCESS_TOKEN")

    async def invalid_reason(self, *, record):
        """清理未知同样逐入口阻止执行，不能等下一次维护循环。"""
        return self.due(record=record, now=datetime.now(UTC)) or ("CLEANUP_UNKNOWN" if await self.cleanup(grant_id=record["grant_id"]) == "UNKNOWN" else None)

    async def cleanup(self, *, grant_id):
        records = await self.store.grant_sessions(grant_id=grant_id)
        if any(item.get("cleanup") == "UNKNOWN" or (item["state"] in TERMINAL and item.get("cleanup") != "COMPLETE") for item in records):
            return "UNKNOWN"
        if any(item["state"] not in TERMINAL or item.get("cleanup") != "COMPLETE" for item in records) or await self.store.pending_opens(grant_id=grant_id):
            return "PENDING"
        return "COMPLETE"

    async def view(self, *, record):
        inflight = record["state"] == "HELD" and self.inflight(grant_id=record["grant_id"], now=datetime.now(UTC))
        return GrantView(
            **{key: record[key] for key in ("grant_id", "node_id", "state", "created_at", "expires_at", "last_activity_at", "idle_timeout_seconds", "released_at", "close_reason")},
            inflight=inflight,
            idle_deadline_at=None if inflight else datetime.fromisoformat(record["last_activity_at"]) + timedelta(seconds=record["idle_timeout_seconds"]),
            cleanup=await self.cleanup(grant_id=record["grant_id"]),
            resolution=await self.store.grant_resolution(grant_id=record["grant_id"]),
        )

    async def claim(self, *, node_id, token, request: GrantRequest):
        self.authorize_hub(token=token)
        digest = hashlib.sha256(json.dumps(request.model_dump(exclude={"request_id"}), sort_keys=True).encode()).hexdigest()
        async with self.nodes.lock:
            old = await self.store.claim_request(node_id=node_id, request_id=request.request_id)
            if old is not None:
                if old["request_digest"] != digest:
                    raise ServiceError(status=409, code="REQUEST_ID_CONFLICT")
                return {"grant_id": old["grant_id"], "node_id": node_id, "state": old["state"], "token_available": False}, False
            seconds = self.duration(seconds=request.lease_seconds)
            if self.settings.public_url is None:
                raise ServiceError(status=503, code="PUBLIC_URL_REQUIRED")
            node = await self.store.node(node_id=node_id)
            if node is None:
                raise ServiceError(status=404, code="NODE_NOT_FOUND")
            if any(item["node_id"] == node_id for item in await self.store.active_grants()):
                raise ServiceError(status=409, code="NODE_LEASE_BUSY")
            if await self.store.node_unclean(node_id=node_id):
                raise ServiceError(status=409, code="NODE_CLEANUP_REQUIRED")
            now = datetime.now(UTC)
            node_view = self.nodes._node_view(node=node, now=now)
            self.available(view=node_view, fail=True)
            access_token = secrets.token_urlsafe(48)
            record = {
                "grant_id": f"grant_{uuid4().hex}", "node_id": node_id,
                "token_hash": token_hash(token=access_token), "request_id": request.request_id,
                "request_digest": digest, "created_at": now.isoformat(),
                "expires_at": (now + timedelta(seconds=seconds)).isoformat(),
                "last_activity_at": now.isoformat(), "idle_timeout_seconds": self.settings.grant_idle_timeout_seconds,
            }
            try:
                await self.store.create_grant(values=record)
            except sqlite3.IntegrityError:
                raise ServiceError(status=409, code="NODE_LEASE_BUSY") from None
            record = await self.store.grant(grant_id=record["grant_id"])
            view = await self.view(record=record)
            access = {"hub_url": self.settings.public_url, "node_id": node_id, "grant_id": view.grant_id, "access_token": access_token, "expires_at": view.model_dump(mode="json")["expires_at"]}
            return GrantCreated(**view.model_dump(), access_token=access_token, access_config=access), True

    def available(self, *, view, fail=False):
        code = None
        if view.connection_status != "ONLINE":
            code = "NODE_OFFLINE"
        else:
            resources = view.capabilities.resources if view.capabilities else []
            backends = {item.name: item for item in view.capabilities.backends} if view.capabilities else {}
            eligible = any(
                item.readiness == "READY" and item.occupancy == "FREE" and item.methods and item.tool_api_version == 1
                and (item.kind != "BORROWED_CHROME_CDP" or item.authorization_scope == "BROWSER_INSTANCE")
                and item.backend in backends and backends[item.backend].runtime_version
                and backends[item.backend].coverage_status == "SUPPORTED"
                for item in resources
            )
            if not eligible or any(item.occupancy != "FREE" for item in resources):
                code = "NODE_NOT_READY"
        if fail and code:
            raise ServiceError(status=409, code=code)
        return code is None

    async def pool(self, *, token):
        self.authorize_hub(token=token)
        leases = {item["node_id"]: item for item in await self.store.active_grants()}
        result = []
        for view in await self.nodes.overview():
            record = leases.get(view.node_id)
            result.append({**view.model_dump(mode="json"), "lease": {"state": record["state"] if record else "UNCLAIMED", "claimable": record is None and self.available(view=view) and not await self.store.node_unclean(node_id=view.node_id)}})
        return {"nodes": result}

    async def status(self, *, grant_id, token):
        record = await self.holder(grant_id=grant_id, token=token)
        reason = await self.invalid_reason(record=record) if record["state"] == "HELD" else None
        if reason:
            await self.begin_release(grant_id=grant_id, reason=reason)
        await self.reconcile(grant_id=grant_id)
        return await self.view(record=await self.store.grant(grant_id=grant_id))

    async def renew(self, *, grant_id, token, seconds):
        await self.holder(grant_id=grant_id, token=token)
        seconds = self.duration(seconds=seconds)
        async with self.nodes.lock:
            record = await self.resolve(token=token)
            expires = max(datetime.fromisoformat(record["expires_at"]), datetime.now(UTC) + timedelta(seconds=seconds))
            await self.store.update_grant(grant_id=grant_id, expires_at=expires.isoformat())
            return await self.view(record=await self.store.grant(grant_id=grant_id))

    async def release(self, *, grant_id, token):
        record = await self.holder(grant_id=grant_id, token=token)
        reason = self.due(record=record, now=datetime.now(UTC)) or "RELEASED_BY_HOLDER"
        await self.begin_release(grant_id=grant_id, reason=reason)
        await self.reconcile(grant_id=grant_id)
        return await self.view(record=await self.store.grant(grant_id=grant_id))

    def schedule(self, *, grant_id, reason):
        if grant_id not in self.reclaims:
            task = asyncio.create_task(self.reclaim(grant_id=grant_id, reason=reason))
            self.reclaims[grant_id] = task
            task.add_done_callback(lambda done: self.reclaim_finished(grant_id=grant_id, task=done))

    def reclaim_finished(self, *, grant_id, task):
        self.reclaims.pop(grant_id, None)
        if not task.cancelled():
            task.exception()

    async def begin_release(self, *, grant_id, reason):
        async with self.nodes.lock:
            record = await self.store.grant(grant_id=grant_id)
            if record["state"] == "HELD":
                await self.store.update_grant(grant_id=grant_id, state="RELEASING", close_reason=reason, revoked_at=datetime.now(UTC).isoformat())
                self.activities.pop(grant_id, None)
        if record["state"] != "RELEASED":
            self.schedule(grant_id=grant_id, reason=reason)

    async def reclaim(self, *, grant_id, reason):
        await self.begin_release(grant_id=grant_id, reason=reason)
        affected = [session for session in self.sessions.sessions.values() if session.view.grant_id == grant_id]
        await asyncio.gather(*(self.sessions.close(session=session, reason=reason) for session in affected))
        await self.reconcile(grant_id=grant_id)

    async def reconcile(self, *, grant_id):
        async with self.nodes.lock:
            record = await self.store.grant(grant_id=grant_id)
            if record["state"] not in {"RELEASING", "QUARANTINED"}:
                return
            cleanup = await self.cleanup(grant_id=grant_id)
            if cleanup == "COMPLETE":
                await self.store.update_grant(grant_id=grant_id, state="RELEASED", released_at=datetime.now(UTC).isoformat())
            elif cleanup == "UNKNOWN":
                await self.store.update_grant(grant_id=grant_id, state="QUARANTINED")

    async def activity_started(self, *, grant_id, key, deadline, refresh=True):
        """调用方在节点锁内受理真实执行后调用，键保证重复请求不续命。"""
        self.activities.setdefault(grant_id, {})[key] = deadline
        if refresh:
            await self.store.update_grant(grant_id=grant_id, last_activity_at=datetime.now(UTC).isoformat())

    async def activity_finished(self, *, grant_id, key, success=True):
        values = self.activities.get(grant_id, {})
        if values.pop(key, None) is not None and success:
            record = await self.store.grant(grant_id=grant_id)
            if record["state"] == "HELD":
                await self.store.update_grant(grant_id=grant_id, last_activity_at=datetime.now(UTC).isoformat())

    async def cleaned(self, *, grant_id):
        """仅首次实际清理完成刷新活动，重复关闭报告不续命。"""
        record = await self.store.grant(grant_id=grant_id)
        if record["state"] == "HELD" and self.due(record=record, now=datetime.now(UTC)) is None:
            await self.store.update_grant(grant_id=grant_id, last_activity_at=datetime.now(UTC).isoformat())

    async def start(self):
        await self.sweep()
        self.task = asyncio.create_task(self.maintenance())

    async def sweep(self):
        for record in await self.store.active_grants():
            if record["state"] == "HELD":
                reason = await self.invalid_reason(record=record)
                if reason:
                    await self.begin_release(grant_id=record["grant_id"], reason=reason)
            else:
                self.schedule(grant_id=record["grant_id"], reason=record["close_reason"])
                await self.reconcile(grant_id=record["grant_id"])

    async def maintenance(self):
        while True:
            await asyncio.sleep(0.25)
            await self.sweep()

    async def shutdown(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        await asyncio.gather(*list(self.reclaims.values()), return_exceptions=True)
