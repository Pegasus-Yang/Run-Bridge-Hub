"""真实 MCP HTTP 传输、base64 解码及总量边界，不启动浏览器。"""

import base64
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from runbridge_hub.browser_tools import UPLOAD_LIMIT
from runbridge_hub.mcp_server import HTTP_REQUEST_LIMIT
from test_mcp import mcp_client, rpc
from test_r1 import grant


@pytest.fixture
def upload(mcp_client, monkeypatch):
    """仅替换页面驱动，保留真实鉴权、HTTP 限额和工具校验。

    :returns: 授权客户端与文件输入记录器。
    """
    locator = SimpleNamespace(count=AsyncMock(return_value=1), set_input_files=AsyncMock())
    @asynccontextmanager
    async def page(**kwargs):
        yield SimpleNamespace(locator=lambda **kw: locator)
    monkeypatch.setattr(mcp_client.app.state.browsers, "page", page)
    return SimpleNamespace(client=mcp_client, access=grant(client=mcp_client), locator=locator)


def file(*, size, name="测试.bin"):
    """构造确定二进制内容。

    :returns: 文件原始字节及 MCP 数据。
    """
    raw = bytes(range(256)) * (size // 256) + bytes(range(size % 256))
    return raw, {"name": name, "mime_type": "application/octet-stream", "data": base64.b64encode(raw).decode()}


def request(*, upload, files, protocol="2026-07-28"):
    """经过 /mcp 入口发送上传请求。

    :returns: 真实 HTTP 响应。
    """
    return rpc(client=upload.client, token=upload.access["access_token"], method="tools/call", params={"name": "browser_file_upload", "arguments": {"session_id": "fixture_session", "page_id": "fixture_page", "target": {"by": "css", "value": "input[type=file]"}, "files": files}}, protocol=protocol)


@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
@pytest.mark.parametrize("sizes", [[UPLOAD_LIMIT], [UPLOAD_LIMIT // 2, UPLOAD_LIMIT // 2]])
def test_http_accepts_single_and_multiple_files_at_exact_limit(upload, sizes, protocol):
    values = [file(size=size, name=f"文件{index}.bin") for index, size in enumerate(sizes)]
    response = request(upload=upload, files=[value[1] for value in values], protocol=protocol)
    assert response.status_code == 200 and len(response.request.content) > 4 * 1024 * 1024
    result = response.json()["result"]
    assert not result.get("isError", False)
    assert result["structuredContent"]["files"] == [value[1]["name"] for value in values]
    actual = upload.locator.set_input_files.call_args.kwargs["files"]
    assert [value["buffer"] for value in actual] == [value[0] for value in values]
    assert sum(len(value["buffer"]) for value in actual) == UPLOAD_LIMIT


@pytest.mark.parametrize("sizes", [[UPLOAD_LIMIT + 1], [UPLOAD_LIMIT // 2, UPLOAD_LIMIT // 2 + 1]])
def test_http_rejects_decoded_total_over_limit_before_page_dispatch(upload, sizes):
    response = request(upload=upload, files=[file(size=size)[1] for size in sizes])
    assert response.status_code == 200
    result = response.json()["result"]
    assert result["isError"] and result["structuredContent"] == {"code": "UPLOAD_TOO_LARGE", "execution_outcome": "NOT_STARTED"}
    upload.locator.set_input_files.assert_not_awaited()


def test_invalid_base64_never_dispatches_upload(upload):
    response = request(upload=upload, files=[{"name": "invalid.bin", "mime_type": "application/octet-stream", "data": "%%%"}])
    assert response.status_code == 200
    assert response.json()["result"]["structuredContent"]["code"] == "INVALID_UPLOAD_DATA"
    upload.locator.set_input_files.assert_not_awaited()


def test_empty_file_list_clears_input(upload):
    response = request(upload=upload, files=[])
    assert response.status_code == 200 and response.json()["result"]["structuredContent"]["files"] == []
    assert upload.locator.set_input_files.call_args.kwargs["files"] == []


def test_http_still_rejects_oversized_encoded_request(upload):
    response = request(upload=upload, files=[{"name": "oversized.bin", "mime_type": "application/octet-stream", "data": "A" * HTTP_REQUEST_LIMIT}])
    assert response.status_code == 413 and len(response.request.content) > HTTP_REQUEST_LIMIT
    upload.locator.set_input_files.assert_not_awaited()
