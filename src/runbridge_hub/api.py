"""节点登记、许可与能力查询的管理 HTTP 接口。"""

from fastapi import APIRouter, Header, Request, Response
from fastapi.responses import JSONResponse

from runbridge_hub.protocol import GrantCreated, GrantRequest, GrantView, Registration, RegistrationResult, SessionCreate, SessionView
from runbridge_hub.security import bearer_token
from runbridge_hub.visual_protocol import NodeQueryView, SessionQueryView
from runbridge_hub.tool_contract import CommandInput, catalog


router = APIRouter(prefix="/v1")
execution_router = APIRouter(prefix="/v2")


@router.post("/nodes/register", response_model=RegistrationResult)
async def register(body: Registration, request: Request, response: Response, authorization: str | None = Header(default=None)):
    """登记节点，不覆盖既有身份。

    :returns: 节点 ID 和是否新建。
    """
    result = await request.app.state.service.register(request=body, token=bearer_token(header=authorization))
    response.status_code = 201 if result.created else 200
    return result


@router.post("/nodes/{node_id}/grants", response_model=GrantCreated, status_code=201)
async def create_grant(node_id: str, body: GrantRequest, request: Request, authorization: str | None = Header(default=None)):
    """为节点签发访问许可。

    :returns: 包含一次性交付凭据的许可。
    """
    return await request.app.state.service.create_grant(node_id=node_id, token=bearer_token(header=authorization), request=body)


@router.get("/nodes/{node_id}/grants", response_model=list[GrantView])
async def list_grants(node_id: str, request: Request, authorization: str | None = Header(default=None)):
    """节点所有者查询许可元数据。

    :returns: 不含凭据的许可列表。
    """
    service = request.app.state.service
    await service.authorize_owner(node_id=node_id, token=bearer_token(header=authorization))
    records = await service.store.grants(node_id=node_id)
    return [GrantView.model_validate(obj={field: record[field] for field in GrantView.model_fields}) for record in records]


@router.delete("/nodes/{node_id}/grants/{grant_id}", status_code=204)
async def revoke_grant(node_id: str, grant_id: str, request: Request, authorization: str | None = Header(default=None)):
    """节点所有者撤销许可。

    :returns: 空响应。
    """
    await request.app.state.sessions.revoke(node_id=node_id, grant_id=grant_id, token=bearer_token(header=authorization))
    return Response(status_code=204)


@router.get("/nodes/{node_id}", response_model=NodeQueryView)
@router.get("/nodes/{node_id}/capabilities", response_model=NodeQueryView)
async def inspect_node(node_id: str, request: Request, authorization: str | None = Header(default=None)):
    """按调用许可返回节点与能力视图。

    :returns: 带新鲜度和连接代次的视图。
    """
    token = bearer_token(header=authorization)
    view = await request.app.state.service.query(node_id=node_id, token=token)
    visual = await request.app.state.visual.node_view(view=view, token=token)
    return NodeQueryView(**view.model_dump(), visual=visual)


@execution_router.post("/nodes/{node_id}/sessions", response_model=SessionView, status_code=201)
async def create_session(node_id: str, body: SessionCreate, request: Request, authorization: str | None = Header(default=None)):
    """准备工具会话，并返回该会话拥有的对象引用。

    :returns: 会话视图。
    """
    return await request.app.state.sessions.create(node_id=node_id, token=bearer_token(header=authorization), request=body)


@execution_router.get("/sessions/{session_id}", response_model=SessionQueryView)
async def inspect_session(session_id: str, request: Request, authorization: str | None = Header(default=None)):
    """查询同一许可创建的会话。

    :returns: 不含秘密的会话元数据。
    """
    view = await request.app.state.sessions.query(session_id=session_id, token=bearer_token(header=authorization))
    return SessionQueryView(**view.model_dump(), visual=request.app.state.visual.describe(view=view))


@execution_router.delete("/sessions/{session_id}", response_model=SessionView)
async def release_session(session_id: str, request: Request, authorization: str | None = Header(default=None)):
    """幂等释放并返回实际清理状态。

    :returns: 会话与清理状态。
    """
    return await request.app.state.sessions.release(session_id=session_id, token=bearer_token(header=authorization))


@execution_router.get("/nodes/{node_id}/tools")
async def tools(node_id: str, request: Request, authorization: str | None = Header(default=None)):
    """返回许可内的工具、资源、参数和默认值声明。"""
    view = await request.app.state.service.query(node_id=node_id, token=bearer_token(header=authorization))
    resources = view.capabilities.resources if view.capabilities else []
    tools = {}
    for resource in resources:
        methods = catalog(tool=resource.tool)
        entry = tools.setdefault(resource.tool, {"tool_api_version": resource.tool_api_version, "methods": {}})
        entry["methods"].update({name: methods[name] for name in resource.methods if name in methods})
    return {"protocol_version": 2, "node": view.model_dump(mode="json"), "tools": tools,
            "resources": [item.model_dump(mode="json") for item in resources]}


@execution_router.post("/sessions/{session_id}/commands")
async def command(session_id: str, body: CommandInput, request: Request, authorization: str | None = Header(default=None)):
    value = await request.app.state.commands.submit(session_id=session_id, token=bearer_token(header=authorization), request=body)
    return JSONResponse(status_code=200 if value["status"] in {"SUCCEEDED", "FAILED", "UNKNOWN"} else 202, content=value)


@execution_router.get("/sessions/{session_id}/commands/{request_id}")
async def command_status(session_id: str, request_id: str, request: Request, authorization: str | None = Header(default=None)):
    return await request.app.state.commands.query(session_id=session_id, request_id=request_id, token=bearer_token(header=authorization))
