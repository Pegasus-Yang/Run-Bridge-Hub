"""RunBridge Hub 的凭据生成与单 Worker 启动入口。"""

import argparse
import sys
from pathlib import Path

import uvicorn
from pydantic import ValidationError

from runbridge_hub.app import create_app
from runbridge_hub.tool_contract import MAX_MESSAGE
from runbridge_hub.security import generate_token_file
from runbridge_hub.server import HubServer
from runbridge_hub.startup import ServeSettings


def main() -> None:
    """执行 Hub 命令，启动成功后输出总览只读口令和访问链接。"""
    parser = argparse.ArgumentParser(
        prog="runbridge-hub", description="RunBridge 节点管理与连接网关"
    )
    commands = parser.add_subparsers(dest="command", required=True)
    generate = commands.add_parser("generate-token", help="生成独立随机凭据文件，可用于登记或总览只读访问")
    generate.add_argument("--output", type=Path, required=True)
    serve = commands.add_parser(
        "serve", help="启动单 Worker Hub", argument_default=argparse.SUPPRESS
    )
    serve.add_argument(
        "--settings", type=Path, help="读取 Hub YAML，不能混用其他启动参数"
    )
    serve.add_argument("--host", help="监听地址，默认 127.0.0.1")
    serve.add_argument("--port", type=int, help="监听端口，默认 8787")
    serve.add_argument(
        "--db-path",
        dest="database_path",
        type=Path,
        help="SQLite 路径，默认 .runbridge/hub.sqlite3",
    )
    serve.add_argument("--enrollment-token-file", type=Path)
    serve.add_argument(
        "--disable-web", dest="web_enabled", action="store_false",
        help="关闭默认启用的节点总览页面、静态资源和只读状态接口",
    )
    serve.add_argument(
        "--web-token-file", type=Path,
        help="独立的总览只读口令文件；未配置时使用环境变量或自动生成 web.token",
    )
    serve.add_argument(
        "--heartbeat-interval",
        dest="heartbeat_interval_seconds",
        type=float,
        help="心跳间隔秒数，默认 30",
    )
    serve.add_argument(
        "--heartbeat-timeout",
        dest="heartbeat_timeout_seconds",
        type=float,
        help="失联超时秒数，默认 90",
    )
    serve.add_argument(
        "--enable-mcp",
        dest="mcp_enabled",
        action="store_true",
        help="启用需要 mcp 可选依赖的 /mcp 工具入口",
    )
    serve.add_argument(
        "--mcp-allowed-host",
        dest="mcp_allowed_hosts",
        action="append",
        help="额外允许的 MCP Host，可重复，端口可用 :*",
    )
    serve.add_argument(
        "--mcp-allowed-origin",
        dest="mcp_allowed_origins",
        action="append",
        help="允许的浏览器 Origin，可重复",
    )
    args = parser.parse_args()
    try:
        if args.command == "generate-token":
            generate_token_file(path=args.output)
            print(f"凭据文件已保存：{args.output}")
            return
        options = {
            key: value
            for key, value in vars(args).items()
            if key not in {"command", "settings"}
        }
        settings_file = getattr(args, "settings", None)
        if settings_file is not None and options:
            parser.error("使用 --settings 时不能混用其他启动参数；请统一写入 YAML")
        startup = (
            ServeSettings.load(path=settings_file)
            if settings_file is not None
            else ServeSettings.model_validate(options)
        )
        settings = startup.hub_settings()
        app = create_app(settings=settings)
    except ValidationError as error:
        fields = ", ".join(
            ".".join(str(part) for part in item["loc"])
            for item in error.errors()
            if item["loc"]
        )
        parser.error(
            f"配置无效：请检查 {fields or '凭据长度、心跳间隔及 MCP 允许列表'}；输入值已隐藏"
        )
    except ModuleNotFoundError:
        parser.error(
            "MCP 依赖未安装：请安装 runbridge-hub[mcp] 或执行 uv sync --extra mcp"
        )
    except (OSError, ValueError) as error:
        print(f"配置失败：{error}", file=sys.stderr)
        raise SystemExit(2) from None
    websocket_protocol = "websockets"
    if settings.web_enabled:
        from runbridge_hub.transport import ControlWebSocketProtocol

        websocket_protocol = ControlWebSocketProtocol

    config = uvicorn.Config(
        app=app,
        host=startup.host,
        port=startup.port,
        workers=1,
        loop="asyncio",
        ws=websocket_protocol,
        ws_max_size=MAX_MESSAGE,
        ws_max_queue=4,
    )
    server = HubServer(config=config)
    try:
        server.run()
    except KeyboardInterrupt:
        pass
    if not server.started:
        # 沿用 Uvicorn 单 Worker 启动失败的退出码。
        raise SystemExit(3)
