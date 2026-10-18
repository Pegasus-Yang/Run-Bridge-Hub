"""只用 Python 标准库调用 RunBridge HTTP，不导入浏览器 SDK。"""

import argparse
import base64
import json
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def run(
    *,
    access_file: Path,
    resource_id: str,
    url: str,
    screenshot: Path,
    page_url: str | None = None,
) -> dict:
    """创建会话、读取真实页面、保存图片，并确认释放。

    :param access_file: Node 所有者交付的访问 JSON。
    :param resource_id: 所有者交付说明中的资源 ID。
    :param url: 目标业务网页地址。
    :param screenshot: 调用方本机的截图输出文件。
    :param page_url: 借用模式有多个页面时用于唯一选页的精确 URL。
    :returns: 无秘密的验证结果。
    """
    access = json.loads(access_file.read_text(encoding="utf-8"))

    def request(*, method, path, body=None):
        data = json.dumps(body).encode() if body is not None else None
        headers = {
            "Authorization": f"Bearer {access['access_token']}",
            "Content-Type": "application/json",
        }
        try:
            with urlopen(
                Request(
                    url=access["hub_url"].rstrip("/") + path,
                    data=data,
                    headers=headers,
                    method=method,
                ),
                timeout=40,
            ) as response:
                return json.load(response)
        except HTTPError as error:
            value = json.load(error)
            raise RuntimeError(
                f"HTTP_{error.code}:{value.get('code', 'REQUEST_FAILED')}"
            ) from None

    open_id = f"open_{uuid4().hex}"
    try:
        session = request(
            method="POST",
            path=f"/v2/nodes/{access['node_id']}/sessions",
            body={
                "resource_id": resource_id,
                "tool": "playwright",
                "request_id": open_id,
                "lease_seconds": 120,
            },
        )
    except Exception:
        raise RuntimeError(
            f"创建结果未确认；可用相同创建 request_id 查询分配：{open_id}"
        ) from None
    sid = session["session_id"]

    def command(*, method, target, params=None):
        request_id = f"cmd_{uuid4().hex}"
        try:
            value = request(
                method="POST",
                path=f"/v2/sessions/{sid}/commands",
                body={
                    "request_id": request_id,
                    "method": method,
                    "target": target,
                    "params": params or {},
                },
            )
            deadline = time.monotonic() + 35
            while (
                value["status"] not in {"SUCCEEDED", "FAILED", "UNKNOWN"}
                and time.monotonic() < deadline
            ):
                time.sleep(0.1)
                value = request(
                    method="GET", path=f"/v2/sessions/{sid}/commands/{request_id}"
                )
            if value["status"] != "SUCCEEDED" or value.get("result") is None:
                code = (value.get("error") or {}).get("code", "REQUEST_IN_PROGRESS")
                raise RuntimeError(code)
            return value["result"]
        except Exception:
            raise RuntimeError(
                f"动作结果需查询，不得盲目重试：session_id={sid}, request_id={request_id}"
            ) from None

    try:
        if session["state"] not in {"READY", "ACTIVE"}:
            raise RuntimeError("SESSION_NOT_ACTIVE")
        pages = session["objects"]["pages"]
        candidates = (
            [page for page in pages if page["url"] == page_url]
            if page_url is not None
            else [
                page
                for page in pages
                if page["id"] == session["objects"]["default_page_id"]
            ]
        )
        if len(candidates) != 1:
            raise RuntimeError("需要所有者提供可唯一确认的 --page-url")
        target = {"type": "page", "id": candidates[0]["id"]}
        navigation = command(method="page.goto", target=target, params={"url": url})[
            "value"
        ]
        title = command(method="page.title", target=target)["value"]
        image = command(method="page.screenshot", target=target)
        png = base64.b64decode(image["data"], validate=True)
        if len(png) != image["size"] or not png.startswith(b"\x89PNG\r\n\x1a\n"):
            raise RuntimeError("INVALID_SCREENSHOT")
        screenshot.write_bytes(png)
    finally:
        closed = request(method="DELETE", path=f"/v2/sessions/{sid}")
        if closed["cleanup"] != "COMPLETE":
            raise RuntimeError(
                f"清理未确认：session_id={sid}, cleanup={closed['cleanup']}"
            )
    return {
        "session_id": sid,
        "request_id": open_id,
        "url": navigation["url"],
        "title": title,
        "screenshot": str(screenshot),
        "state": closed["state"],
        "cleanup": closed["cleanup"],
    }


def main():
    parser = argparse.ArgumentParser(description="RunBridge 项目 HTTP 调用示例")
    parser.add_argument("--access-file", type=Path, required=True)
    parser.add_argument("--resource-id", default="chromium")
    parser.add_argument("--url", required=True)
    parser.add_argument("--page-url")
    parser.add_argument("--screenshot", type=Path, default=Path("page.png"))
    args = parser.parse_args()
    try:
        value = run(
            access_file=args.access_file,
            resource_id=args.resource_id,
            url=args.url,
            screenshot=args.screenshot,
            page_url=args.page_url,
        )
    except Exception as error:
        parser.exit(status=1, message=f"示例未完成：{error}\n")
    print(json.dumps(value, ensure_ascii=False))


if __name__ == "__main__":
    main()
