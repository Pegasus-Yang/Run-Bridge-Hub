"""MCP 的项目引用与工具指令适配；不加载 Playwright。"""

from uuid import uuid4

from runbridge_hub.protocol import SessionCreate
from runbridge_hub.service import ServiceError
from runbridge_hub.tool_contract import CommandInput, Target


class BrowserError(ServiceError):
    def __init__(
        self, *, code: str, outcome: str = "NOT_STARTED", request_id: str | None = None
    ):
        self.outcome = outcome
        self.request_id = request_id
        super().__init__(status=409, code=code)


class BrowserService:
    """将明确 MCP 参数转换为项目调用，不持有远程 SDK 对象。"""

    def __init__(self, *, sessions, commands, visual):
        self.sessions = sessions
        self.commands = commands
        self.visual = visual

    async def start(self):
        pass

    async def open(
        self, *, node_id, token, resource_id=None, lease_seconds=300, request_id=None
    ):
        grant = await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        if (
            resource_id is not None
            and grant["resource_ids"] is not None
            and resource_id not in grant["resource_ids"]
        ):
            raise BrowserError(code="RESOURCE_OUTSIDE_GRANT")
        view = await self.sessions.nodes.query(node_id=node_id, token=token)
        resources = [
            item
            for item in (view.capabilities.resources if view.capabilities else [])
            if item.kind == "MANAGED_CHROMIUM" and item.tool == "playwright"
        ]
        if resource_id is None:
            if len(resources) != 1:
                raise BrowserError(code="MANAGED_RESOURCE_REQUIRED")
            resource_id = resources[0].resource_id
        if resource_id not in {item.resource_id for item in resources}:
            raise BrowserError(code="MANAGED_RESOURCE_REQUIRED")
        request_id = request_id or f"open_{uuid4().hex}"
        try:
            session = await self.sessions.create(
                node_id=node_id,
                token=token,
                request=SessionCreate(
                    resource_id=resource_id,
                    request_id=request_id,
                    lease_seconds=lease_seconds,
                ),
            )
            # 启动完成即通过一条只读项目指令激活，保留 MCP 启动后可观察画面的行为。
            if session.state in {"READY", "ACTIVE"}:
                await self.call(
                    session_id=session.session_id,
                    token=token,
                    method="runbridge.session_state",
                    target=Target(type="session", id=session.session_id),
                )
                session = await self.sessions.query(
                    session_id=session.session_id, token=token
                )
        except ServiceError as error:
            record = await self.sessions.nodes.store.mcp_request(
                key=(grant["grant_id"], node_id, request_id)
            )
            outcome = record.get("execution_outcome") if record else None
            raise BrowserError(
                code=error.code,
                outcome=outcome
                or (
                    "OUTCOME_UNKNOWN"
                    if record and record["session_id"]
                    else "NOT_STARTED"
                ),
                request_id=request_id,
            ) from None
        return {
            "session": session.model_dump(mode="json"),
            "page_id": session.objects.get("default_page_id"),
            "request_id": request_id,
        }

    async def call(
        self, *, session_id, token, method, target, params=None, request_id=None
    ):
        request_id = request_id or f"cmd_{uuid4().hex}"
        try:
            response = await self.commands.submit(
                session_id=session_id,
                token=token,
                request=CommandInput(
                    request_id=request_id,
                    method=method,
                    target=target,
                    params=params or {},
                ),
            )
        except ServiceError as error:
            if error.status == 401:
                raise BrowserError(
                    code="OPERATION_INTERRUPTED",
                    outcome="OUTCOME_UNKNOWN",
                    request_id=request_id,
                ) from None
            raise
        if response["status"] != "SUCCEEDED" or response.get("result") is None:
            code = (response.get("error") or {}).get("code", "REQUEST_IN_PROGRESS")
            code = {
                "ACTION_TIMEOUT": "OPERATION_TIMEOUT",
                "OBJECT_NOT_FOUND": "PAGE_NOT_FOUND",
                "OBJECT_CLOSED": "PAGE_NOT_FOUND",
                "RESULT_UNKNOWN": "OPERATION_INTERRUPTED",
            }.get(code, code)
            raise BrowserError(
                code=code, outcome=response["execution_outcome"], request_id=request_id
            )
        result = response["result"]
        if result["kind"] == "binary":
            return {**result, "request_id": request_id}
        value = result["value"]
        return (
            {**value, "request_id": request_id}
            if isinstance(value, dict)
            else {"value": value, "request_id": request_id}
        )

    async def status(self, *, session_id, token):
        view = await self.sessions.query(session_id=session_id, token=token)
        return {
            "session": view.model_dump(mode="json"),
            "pages": view.objects.get("pages", []),
            "request_id": view.request_id,
            "visual": self.visual.describe(view=view).model_dump(mode="json"),
        }

    async def listing(self, *, node_id, token, request_id=None):
        grant = await self.sessions.nodes.authorize_access(node_id=node_id, token=token)
        record = (
            await self.sessions.nodes.store.mcp_request(
                key=(grant["grant_id"], node_id, request_id)
            )
            if request_id
            else None
        )
        if request_id:
            ids = [record["session_id"]] if record and record["session_id"] else []
        else:
            ids = [
                item.view.session_id
                for item in self.sessions.sessions.values()
                if item.view.node_id == node_id
                and item.view.grant_id == grant["grant_id"]
            ]
        values = [
            await self.status(session_id=session_id, token=token) for session_id in ids
        ]
        result = {"sessions": values}
        if request_id:
            result["request"] = {
                "request_id": request_id,
                "node_id": node_id,
                "grant_id": grant["grant_id"],
                "state": record["state"] if record else "NOT_FOUND",
                "session_id": record["session_id"] if record else None,
                "error_code": record["error_code"] if record else None,
                "execution_outcome": record["execution_outcome"] if record else None,
            }
        return result

    async def shutdown(self):
        pass
