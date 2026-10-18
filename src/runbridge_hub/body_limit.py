"""在 HTTP JSON 解析前限制总请求体，包含没有 Content-Length 的请求。"""

from starlette.responses import JSONResponse

from runbridge_hub.tool_contract import MAX_MESSAGE


class RequestSizeLimit:
    """有界接收请求体，超限时在框架解析输入之前返回 413。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        async def reject():
            await JSONResponse(status_code=413, content={"code": "REQUEST_TOO_LARGE"})(
                scope, receive, send
            )

        for name, value in scope.get("headers", []):
            if (
                name.lower() == b"content-length"
                and value.isdigit()
                and int(value) > MAX_MESSAGE
            ):
                return await reject()
        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            part = message.get("body", b"")
            if len(body) + len(part) > MAX_MESSAGE:
                return await reject()
            body.extend(part)
            if not message.get("more_body", False):
                break
        delivered = False

        async def replay():
            nonlocal delivered
            if delivered:
                return await receive()
            delivered = True
            return {"type": "http.request", "body": bytes(body), "more_body": False}

        await self.app(scope, replay, send)
