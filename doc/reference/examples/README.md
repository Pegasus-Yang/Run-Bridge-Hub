# Hub 接口调用方示例

[文档导航](../../README.md) · [调用方环境](../../user-guide/调用方对接与使用.md) · [画面订阅](../../user-guide/浏览器画面流接入.md)

本目录只提供使用 Hub 公开接口的客户端脚本、展示页面和响应示例。将所需文件复制到调用方自己的 examples/，按对应指南准备独立 .venv；无需克隆或安装 Node 项目。

| 文件 | 用途 | 客户端依赖 |
| --- | --- | --- |
| [mcp_browser.py](mcp_browser.py) | MCP 授权、创建、导航／截图及释放 | Python 3.14、mcp 2.3.0 |
| [执行会话调用.py](执行会话调用.py) | 申请、官方 SDK 接入、读取页面／截图及释放 | httpx、Playwright 1.63.0 |
| [画面流订阅.py](画面流订阅.py) | 查询活动会话、选择目标、保存少量 PNG | httpx、websockets |
| [画面查看示例.html](画面查看示例.html) | 调用方前端认证、解码并展示最新 PNG | WebSocket、Canvas、createImageBitmap |

仅使用 MCP 的独立调用方可在自己的目录安装客户端并执行复制的脚本：

```bash
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python 'mcp==2.3.0' -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
mkdir -p examples artifacts
.venv/bin/python examples/mcp_browser.py --access-file access.json --url https://your-test-system.example/ --screenshot artifacts/page.png
```

先取得有效访问文件、实际远程 MCP 地址和受管理资源。示例从文件安全读取令牌，使用 finally 释放会话；详见 [MCP 指南](../../user-guide/MCP浏览器接入.md)。

Python 示例只调用公开接口，不导入 Hub／Node 内部包。HTML 是调用方页面，不由 Hub 托管；静态目录仅放公开示例，不放访问文件。执行脚本的 --hold-seconds 用于在租期内保持连接，不能延长许可或会话期限。

## 响应示例

| 文件 | 含义 |
| --- | --- |
| [节点查询示例.json](节点查询示例.json) | 节点查询的基础合同，画面字段另见接口参考 |
| [会话状态示例.json](会话状态示例.json) | 基础会话字段，查询还可附带 visual |
| [连接错误示例.json](连接错误示例.json) | 控制连接公开错误示例 |

JSON 中的 ID、时间和端点是演示值。Node 本机浏览器配置格式在 Node 项目维护。
