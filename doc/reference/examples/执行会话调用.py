"""仅使用公开 HTTP 接口和官方 SDK，执行后释放会话。"""

import argparse
import asyncio
import json
import sys
from importlib.metadata import version
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from playwright.async_api import Error, async_playwright


def websocket_url(*, hub_url: str, path: str) -> str:
    """保留 Hub 部署前缀，将 HTTP 基址转为 WebSocket。

    :returns: 不包含凭据的连接地址。
    """
    address = urlsplit(hub_url.rstrip("/"))
    return urlunsplit(("wss" if address.scheme == "https" else "ws", address.netloc, address.path + path, "", ""))


async def execute(*, args) -> None:
    """申请资源，根据返回协议选择官方连接方式。

    :param args: CLI 参数；已有 Chrome 模式只读取指定原页面。
    """
    access = json.loads(args.access_file.read_text(encoding="utf-8"))
    hub = access["hub_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {access['access_token']}"}
    async with httpx.AsyncClient(timeout=40) as client:
        created = await client.post(url=f"{hub}/v1/nodes/{access['node_id']}/sessions", headers=headers,
                                    json={"resource_id": args.resource_id, "client_version": version(distribution_name="playwright"), "lease_seconds": args.lease_seconds})
        created.raise_for_status()
        session = created.json()
        session_url = f"{hub}/v1/sessions/{session['session_id']}"
        print(json.dumps({"session_id": session["session_id"], "state": session["state"], "native_protocol": session["native_protocol"]}, ensure_ascii=False), flush=True)
        try:
            async with async_playwright() as playwright:
                endpoint = websocket_url(hub_url=hub, path=session["native_path"])
                if session["native_protocol"] == "cdp":
                    if not args.page_url:
                        raise ValueError("已有 Chrome 模式需要 --page-url")
                    browser = await playwright.chromium.connect_over_cdp(endpoint_url=endpoint, headers=headers, no_defaults=True, timeout=10000)
                elif session["native_protocol"] == "playwright":
                    browser = await playwright.chromium.connect(endpoint=endpoint, headers=headers, timeout=10000)
                else:
                    raise ValueError("不支持的执行协议")
                try:
                    if session["native_protocol"] == "cdp":
                        pages = [page for context in browser.contexts for page in context.pages if page.url == args.page_url]
                        if len(pages) != 1:
                            raise ValueError("已有页面没有唯一匹配")
                        page = pages[0]
                    else:
                        page = await browser.new_page()
                        await page.goto(url=args.url, wait_until="domcontentloaded")
                    if args.screenshot is not None:
                        args.screenshot.parent.mkdir(parents=True, exist_ok=True)
                        await page.screenshot(path=args.screenshot, full_page=True)
                    response = await client.get(url=session_url, headers=headers)
                    response.raise_for_status()
                    view = response.json()
                    print(json.dumps({"session_id": session["session_id"], "state": view["state"], "title": await page.title(), "visual": view.get("visual")}, ensure_ascii=False), flush=True)
                    # 实际业务动作与断言放在这里，直接使用官方 Page/Locator API。
                    if args.hold_seconds:
                        await asyncio.sleep(delay=args.hold_seconds)
                finally:
                    await browser.close()
        finally:
            released = await client.delete(url=session_url, headers=headers)
            released.raise_for_status()
            result = released.json()
            print(json.dumps({"session_id": session["session_id"], "state": result["state"], "cleanup": result["cleanup"]}, ensure_ascii=False), flush=True)
            if result["cleanup"] != "COMPLETE":
                raise RuntimeError("清理尚未确认，请查询会话")


def main() -> None:
    """运行独立调用示例，不读取 Node 身份文件。"""
    parser = argparse.ArgumentParser(description="RunBridge 官方 SDK 执行示例")
    parser.add_argument("--access-file", type=Path, required=True)
    parser.add_argument("--resource-id", required=True)
    parser.add_argument("--page-url", help="已有 Chrome 中唯一匹配的原页面 URL")
    parser.add_argument("--url", default="data:text/html,<meta charset=utf-8><title>RunBridge</title><h1>Playwright connected</h1>", help="受管理模式中新页面的地址")
    parser.add_argument("--screenshot", type=Path)
    parser.add_argument("--hold-seconds", type=float, default=0, help="保持 ACTIVE，供另一终端订阅画面")
    parser.add_argument("--lease-seconds", type=float, default=300)
    args = parser.parse_args()
    if not 1 <= args.lease_seconds <= 3600 or not 0 <= args.hold_seconds < args.lease_seconds:
        parser.error("租期须为 1–3600 秒，保持时长须小于租期且不小于 0")
    try:
        asyncio.run(execute(args=args))
    except (Error, httpx.HTTPError, OSError, ValueError, KeyError, RuntimeError, KeyboardInterrupt):
        print("调用结束或失败；请检查会话状态与 cleanup，未自动重放动作", file=sys.stderr)
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
