"""RunBridge Hub 的凭据生成与单 Worker 启动入口。"""

import argparse
import os
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from runbridge_hub.app import create_app
from runbridge_hub.tool_contract import MAX_MESSAGE
from runbridge_hub.security import generate_token_file
from runbridge_hub.settings import HubSettings


def main() -> None:
    """执行 Hub 命令，凭据值不放进命令行或输出。"""
    parser = argparse.ArgumentParser(prog="runbridge-hub", description="RunBridge 节点管理与连接网关")
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate-token", help="生成首次登记凭据文件")
    generate.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser("serve", help="启动单 Worker Hub")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.add_argument("--db-path", type=Path, default=Path(".runbridge/hub.sqlite3"))
    serve.add_argument("--enrollment-token-file", type=Path)
    serve.add_argument("--heartbeat-interval", type=float, default=30)
    serve.add_argument("--heartbeat-timeout", type=float, default=90)
    serve.add_argument("--enable-mcp", action="store_true", help="启用需要 mcp 可选依赖的 /mcp 工具入口")
    serve.add_argument("--mcp-allowed-host", action="append", help="额外允许的 MCP Host，可重复，端口可用 :*")
    serve.add_argument("--mcp-allowed-origin", action="append", help="允许的浏览器 Origin，可重复")
    args = parser.parse_args()
    try:
        if args.command == "generate-token":
            generate_token_file(path=args.output)
            print(f"登记凭据已保存：{args.output}")
            return
        token = args.enrollment_token_file.read_text(encoding="utf-8").strip() if args.enrollment_token_file is not None else os.environ.get("RUNBRIDGE_ENROLLMENT_TOKEN")
        if not token:
            raise ValueError("请提供 --enrollment-token-file 或 RUNBRIDGE_ENROLLMENT_TOKEN")
        settings = HubSettings(database_path=args.db_path, enrollment_token=token, heartbeat_interval_seconds=args.heartbeat_interval, heartbeat_timeout_seconds=args.heartbeat_timeout,
                               mcp_enabled=args.enable_mcp,
                               mcp_allowed_origins=args.mcp_allowed_origin or [])
        settings.mcp_allowed_hosts.extend(args.mcp_allowed_host or [])
        settings = HubSettings.model_validate(settings.model_dump())
        app = create_app(settings=settings)
    except ValidationError:
        parser.error("配置无效：请检查凭据长度、心跳间隔及 MCP 地址/允许列表")
    except ModuleNotFoundError:
        parser.error("MCP 依赖未安装：请安装 runbridge-hub[mcp] 或执行 uv sync --extra mcp")
    except (OSError, ValueError) as error:
        print(f"配置失败：{error}", file=sys.stderr)
        raise SystemExit(2) from None
    uvicorn.run(app=app, host=args.host, port=args.port, workers=1, loop="asyncio", ws="websockets", ws_max_size=MAX_MESSAGE, ws_max_queue=4)
