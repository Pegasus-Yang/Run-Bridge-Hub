# RunBridge Hub

**通过 HTTP 或 MCP，使用远程设备上的浏览器。**

RunBridge Hub 是 RunBridge 的服务端：接纳 Node，验证访问许可，分配浏览器会话，把结构化指令路由给 Node 并返回结果。浏览器在 Node 设备上运行；Hub 无需安装 Playwright、Node.js 或浏览器。

[快速开始](doc/user-guide/快速开始.md) · [部署手册](doc/deployment/部署与运行.md) · [参数详解](doc/reference/参数详解.md) · [完整文档](doc/README.md)

## 能做什么

- **统一入口**：HTTP 方法与 MCP 工具共用授权、会话和执行流程，适合程序调用及 Agent 接入。
- **跨机器操作**：Node 主动连接 Hub；调用方不需要直接访问 Node 的浏览器端口。
- **明确授权范围**：节点身份与调用许可分离，可按资源签发独立许可、设置期限和撤销访问。
- **可查询的执行结果**：使用请求 ID 跟踪动作，重复请求去重；断线后可以查询原结果。
- **浏览器画面**：接收 Node 的页面截图流，供调用方观察；浏览器采集仍在 Node 完成。

```text
调用方 HTTP / Agent MCP → Hub 鉴权与路由 ⇄ Node → Python Playwright → 浏览器
```

当前版本 **0.7.0**，与 Node **0.7.0** 配套。提供项目自己的 Playwright 风格调用规则：33 项方法、27 个 MCP 工具。支持范围见[方法表](doc/reference/Playwright方法表.md)；官方 Playwright SDK 的直连接口已退役。

## 快速部署

在 **Hub 机器**上操作。前提是已有 Python **3.14.x**、全局 [uv](https://docs.astral.sh/uv/getting-started/installation/)，并从发布负责人取得 `runbridge_hub-0.7.0-py3-none-any.whl`，保存到 `~/Downloads/`。基础工具准备参考官网；源码构建见开发文档。

创建独立部署目录、安装并生成登记文件：

```bash
mkdir -p ~/runbridge-hub
cd ~/runbridge-hub
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python ~/Downloads/runbridge_hub-0.7.0-py3-none-any.whl -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/runbridge-hub generate-token --output .runbridge/enrollment.token
```

创建 `hub.yaml`。下面允许远程 Node 连接；端口、数据库和心跳采用默认值：

```yaml
host: 0.0.0.0
enrollment_token_file: .runbridge/enrollment.token
```

启动，保留这个终端：

```bash
.venv/bin/runbridge-hub serve --settings hub.yaml
```

另开终端验证：

```bash
curl --fail http://127.0.0.1:8787/health
```

应返回 `{"status":"ok","protocol_version":2}`。将 **Hub 的实际可达基址**（如 `http://hub.example:8787`）和刚生成的 **enrollment.token 文件**私密交给 Node 所有者。Node 的安装步骤在 Node 项目中；此时 Hub 已就绪，浏览器验证要等 Node 接入。

需要 Agent/MCP 时，按[快速开始的 MCP 小节](doc/user-guide/快速开始.md#启用-mcp按需)安装 `[mcp]` 并启用。MCP 客户端在 Hub 本机时，无需配置 `mcp_allowed_hosts`。

## 验证一次浏览器操作

Node 所有者交付 `access.json` 后，可用[标准库 HTTP 示例](doc/reference/examples/执行会话调用.py)完成“打开 Hub 健康页 → 读取页面 → 保存 PNG → 释放会话”。[快速开始](doc/user-guide/快速开始.md#验证一次完整调用node-接入后)使用本部署的健康页，不依赖外部网站；成功时截图显示健康检查 JSON，清理结果为 `COMPLETE`。

Agent 通过 Streamable HTTP 连接 `/mcp`，使用访问文件中的令牌；具体配置见 [MCP 浏览器接入](doc/user-guide/MCP浏览器接入.md)。

## 使用与维护

| 要做的事 | 阅读文档 |
| --- | --- |
| 第一次部署、验证、处理常见错误 | [快速开始](doc/user-guide/快速开始.md) |
| 配置长期运行、交付材料与备份 | [部署与运行](doc/deployment/部署与运行.md) |
| 保存 YAML、查询默认值和适用场景 | [参数详解](doc/reference/参数详解.md)、[带注释 YAML](doc/reference/examples/Hub启动配置.yaml) |
| 编写调用程序、理解对象和请求 ID | [调用方教程](doc/user-guide/调用方对接与使用.md)、[工具调用协议](doc/reference/工具调用协议.md) |
| 观察浏览器画面 | [画面流接入](doc/user-guide/浏览器画面流接入.md) |
| 排查断线、许可、会话与升级问题 | [运行与排障](doc/deployment/运行与排障.md) |

## 开发

源码位于 `src/runbridge_hub/`，使用项目根目录 `.venv`。依赖同步、pytest、构建 wheel 和隔离联调步骤见[本地开发与联调](doc/development/本地开发与联调.md)。

从[代码结构与执行流程](doc/architecture/代码结构与执行流程.md)了解实现，从[文档导航](doc/README.md)查阅当前架构、协议、设计过程和验收记录。报告问题时附上两端版本、已隐藏秘密的配置、错误码和复现步骤；不要提交令牌或私有身份文件。
