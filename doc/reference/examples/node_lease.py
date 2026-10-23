"""标准库示例：用 Hub 认证领取、查询及释放 Node，秘密只写入私有文件。"""

import argparse
import json
import os
import sys
import time
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen
from uuid import uuid4


def call(*, values, path, method="GET", body=None, hub=False):
    """请求实际配置的 Hub 基址，保留反向代理前缀。"""
    token = values["hub_token" if hub else "access_token"]
    request = Request(url=values["hub_url"].rstrip("/") + path,
                      data=json.dumps(body).encode() if body is not None else None,
                      method=method, headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urlopen(request, timeout=20) as response:
            return json.load(response)
    except HTTPError as error:
        try:
            code = json.load(error).get("code", "REQUEST_REJECTED")
        except (ValueError, OSError):
            code = "REQUEST_REJECTED"
        raise ValueError(f"Hub HTTP {error.code}: {code}") from None


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    claim = commands.add_parser("claim")
    claim.add_argument("--hub-auth", type=Path, required=True, help="仅含 hub_url/hub_token 的私有 JSON")
    claim.add_argument("--node-id", required=True)
    claim.add_argument("--output", type=Path, required=True)
    claim.add_argument("--request-id", default=None)
    claim.add_argument("--lease-seconds", type=int)
    for command in (commands.add_parser("status"), commands.add_parser("release")):
        command.add_argument("--access-file", type=Path, required=True)
    args = parser.parse_args()
    if args.command == "claim":
        values = json.loads(args.hub_auth.read_text(encoding="utf-8"))
        if set(values) != {"hub_url", "hub_token"}:
            raise ValueError("Hub 认证文件必须仅包含 hub_url 和 hub_token")
        args.output.parent.mkdir(parents=True, exist_ok=True)
        descriptor = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        access = None
        try:
            request = {"request_id": args.request_id or f"claim_{uuid4().hex}"}
            if args.lease_seconds is not None:
                request["lease_seconds"] = args.lease_seconds
            result = call(values=values, path=f"/v1/nodes/{args.node_id}/grants", method="POST", body=request, hub=True)
            if not result.get("token_available"):
                raise ValueError("该申请已受理，原秘密不能重新下载；使用原访问文件或等待空闲回收")
            access = result["access_config"]
            with os.fdopen(descriptor, "w", encoding="utf-8") as output:
                descriptor = None
                json.dump(access, output, ensure_ascii=False, indent=2)
                output.write("\n")
                output.flush()
                os.fsync(output.fileno())
        except BaseException:
            if descriptor is not None:
                os.close(descriptor)
            args.output.unlink(missing_ok=True)
            if access is not None:
                call(values=access, path=f"/v1/grants/{access['grant_id']}", method="DELETE")
            raise
        print(f"已领取 {access['node_id']}；访问文件：{args.output}；到期：{access['expires_at']}")
        return
    values = json.loads(args.access_file.read_text(encoding="utf-8"))
    path = f"/v1/grants/{values['grant_id']}"
    result = call(values=values, path=path, method="DELETE" if args.command == "release" else "GET")
    if args.command == "release":
        deadline = time.monotonic() + 30
        while result["state"] == "RELEASING" and time.monotonic() < deadline:
            time.sleep(0.2)
            result = call(values=values, path=path)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == "release" and result["state"] != "RELEASED":
        raise ValueError("释放未确认完成，请保留原访问文件查询；QUARANTINED 需设备维护者核查")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, KeyError):
        print("操作失败：请检查文件、网络和 Hub 返回状态；秘密未输出。", file=sys.stderr)
        raise SystemExit(1) from None
