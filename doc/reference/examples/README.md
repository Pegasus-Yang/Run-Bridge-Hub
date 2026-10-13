# 接口数据与完整调用示例

[文档导航](../../README.md) · [调用方指南](../../user-guide/调用方对接与使用.md) · [画面接入](../../user-guide/浏览器画面流接入.md)

## 可运行的调用方示例

| 文件 | 用途 | 依赖 |
| --- | --- | --- |
| [mcp_browser.py](mcp_browser.py) | MCP 授权 → 启动 → 导航/快照/截图 → 释放 | Python 3.14、MCP 2.3.0（含 httpx2） |
| [执行会话调用.py](执行会话调用.py) | 申请 → 根据 native_protocol 连接官方 SDK → 读取页面/截图 → 查询 → 释放 | Python 3.14、httpx、Playwright 1.63.0 |
| [画面流订阅.py](画面流订阅.py) | 查询现有 ACTIVE 会话、列出/选择目标、解包并保存少量 PNG | Python 3.14、httpx、websockets |
| [画面查看示例.html](画面查看示例.html) | 调用方浏览器首消息认证、解码并展示最新 PNG | 支持 WebSocket、Canvas、createImageBitmap 的浏览器 |

Python 示例只调用公开接口，不导入 Hub/Node 内部模块。调用方环境和完整运行命令见指南。HTML 是调用方演示文件，不由 Hub 提供；它不创建会话、不包含令牌，也不执行业务动作。浏览器通过调用方平台或回环 HTTP 读取，不用 data URL；静态目录只放公开示例。具体启动命令及局域网权限说明见画面指南。

安装 Hub `mcp` extra 后可在 Hub 项目根目录试运行 MCP 示例；也可在独立客户端环境安装 `mcp==2.3.0`，无需 Playwright：

```bash
uv run --locked --no-sync python doc/reference/examples/mcp_browser.py --access-file /私有路径/agent-access.json --url https://目标网页 --screenshot /本机路径/page.png
```

需要先在 Hub 开启 `/mcp`，Node 提供新的受管理 Chromium。示例不会打印令牌或网页私有文本，截图保存在指定的客户端本机路径。它在 `finally` 中释放会话，并对未确认清理返回失败。完整工具合同见 [MCP 接入](../../user-guide/MCP浏览器接入.md)。

Python 示例通过 --access-file 读取创建会话的同一许可。执行示例的 --hold-seconds 可让另一终端或 HTML 在该时段内订阅；保持时长小于租期，不能延长许可有效期。省略保持参数时，执行后立即释放，随后订阅已结束会话会失败。

## 原有 JSON 示例

| 文件 | 含义 |
| --- | --- |
| [节点查询示例.json](节点查询示例.json) | R1 基础节点查询字段，0.4.0 的临时 visual 扩展见画面接口 |
| [会话状态示例.json](会话状态示例.json) | 基础 SessionView 字段；查询还会附带 visual |
| [连接错误示例.json](连接错误示例.json) | 控制合同错误示例 |
| [Chrome节点配置.json](Chrome节点配置.json) | 本地固定浏览器实例端点，必须替换为所有者实际授权地址 |
| [Playwright节点配置.json](Playwright节点配置.json) | 受管理 Chromium 运行时与启动配置 |

JSON 中的 ID、时间和端点是合同示例，不是可直接登录的真实部署信息。登记凭据、Node 身份与调用许可的实际原值不写入这些文件。
