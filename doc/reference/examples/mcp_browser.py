"""使用私有对接文件访问 MCP，观察远程网页并可靠释放会话。"""

import argparse
import asyncio
import base64
import json
from pathlib import Path

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def run(*, access_file: Path, url: str, screenshot: Path) -> dict:
    """完成真实 MCP 调用；不输出令牌、原始连接错误或页面私有内容。

    :param access_file: Node 所有者交付的私有对接文件。
    :param url: 要观察的 HTTP(S) 网页。
    :param screenshot: 本机截图输出文件。
    :returns: 无秘密的结束状态。
    """
    access = json.loads(access_file.read_text(encoding="utf-8"))
    async with httpx2.AsyncClient(headers={"Authorization": f"Bearer {access['access_token']}"}, timeout=75) as http:
        transport = streamable_http_client(url=f"{access['hub_url'].rstrip('/')}/mcp", http_client=http)
        async with Client(server=transport) as client:
            async def call(*, name: str, arguments: dict):
                result = await client.call_tool(name=name, arguments=arguments)
                if result.is_error:
                    raise RuntimeError((result.structured_content or {}).get("code", "MCP_TOOL_FAILED"))
                return result

            opened = await call(name="browser_start", arguments={"node_id": access["node_id"]})
            ids = {"session_id": opened.structured_content["session"]["session_id"], "page_id": opened.structured_content["page_id"]}
            try:
                await call(name="browser_navigate", arguments={**ids, "url": url})
                snapshot = await call(name="browser_snapshot", arguments=ids)
                captured = await call(name="browser_screenshot", arguments=ids)
                png = next(item for item in captured.content if item.type == "image")
                screenshot.write_bytes(base64.b64decode(png.data))
            finally:
                stopped = await call(name="browser_stop", arguments={"session_id": ids["session_id"]})
                closed = stopped.structured_content["session"]
                if closed["state"] != "CLOSED" or closed["cleanup"] != "COMPLETE":
                    raise RuntimeError(f"SESSION_END_UNCONFIRMED:{closed['state']}:{closed['cleanup']}")
            return {"session_id": ids["session_id"], "snapshot_characters": len(snapshot.structured_content["snapshot"]), "screenshot": str(screenshot), "state": closed["state"], "cleanup": closed["cleanup"]}


def main() -> None:
    """从客户端本地文件加载凭据，不接受命令行明文 token。"""
    parser = argparse.ArgumentParser(description="RunBridge MCP 远程浏览器示例")
    parser.add_argument("--access-file", type=Path, required=True)
    parser.add_argument("--url", required=True)
    parser.add_argument("--screenshot", type=Path, default=Path("mcp-page.png"))
    args = parser.parse_args()
    try:
        result = asyncio.run(run(access_file=args.access_file, url=args.url, screenshot=args.screenshot))
    except Exception:
        parser.exit(status=1, message="MCP 示例执行失败；请用同一许可查询会话状态，原始错误和凭据未输出。\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
