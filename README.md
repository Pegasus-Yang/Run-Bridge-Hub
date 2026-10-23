# RunBridge Hub

**通过 HTTP 或 MCP，使用远程设备上的浏览器。**

RunBridge Hub 是 RunBridge 的服务端：接纳 Node，验证访问许可，分配浏览器会话，把结构化指令路由给 Node 并返回结果。浏览器在 Node 设备上运行；Hub 无需安装 Playwright、Node.js 或浏览器。

[快速开始](doc/user-guide/快速开始.md) · [部署手册](doc/deployment/部署与运行.md) · [参数详解](doc/reference/参数详解.md) · [完整文档](doc/README.md) · [更新日志](doc/project/版本发布记录.md)

## 能做什么

- **统一入口**：HTTP 方法与 MCP 工具共用授权、会话和执行流程，适合程序调用及 Agent 接入。
- **跨机器操作**：Node 主动连接 Hub；调用方不需要直接访问 Node 的浏览器端口。
- **统一分配使用权**：持有 Hub 凭据即可领取空闲 Node，每个 Node 同时只有一份有效租约；支持续租、释放、到期和空闲回收。
- **可查询的执行结果**：使用请求 ID 跟踪动作，重复请求去重；断线后可以查询原结果。
- **浏览器画面**：接收 Node 的页面截图流，供调用方观察；浏览器采集仍在 Node 完成。
- **节点总览**：默认提供同端口只读页面，查看真实连接、资源占用、支持能力、最近心跳和实测控制通道 RTT；支持筛选、搜索与节点详情，适配桌面和手机。

```text
调用方 HTTP / Agent MCP → Hub 鉴权与路由 ⇄ Node → Python Playwright → 浏览器
```

当前版本 **0.9.1**，兼容 Node **0.8.1**。提供项目自己的 Playwright 风格调用规则：33 项方法、27 个 MCP 工具。支持范围见[方法表](doc/reference/Playwright方法表.md)；官方 Playwright SDK 的直连接口已退役。

## 快速部署

在 **Hub 机器**上操作。前提是已有 Python **3.14.x**、全局 [uv](https://docs.astral.sh/uv/getting-started/installation/)，并从发布负责人取得 `runbridge_hub-0.9.1-py3-none-any.whl`，保存到 `~/Downloads/`。基础工具准备参考官网；源码构建见开发文档。

创建独立部署目录、安装并分别生成登记和资源池申请凭据：

```bash
mkdir -p ~/runbridge-hub
cd ~/runbridge-hub
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python ~/Downloads/runbridge_hub-0.9.1-py3-none-any.whl -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/runbridge-hub generate-token --output .runbridge/enrollment.token
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

创建 `hub.yaml`。下面允许远程 Node 连接；端口、数据库和心跳采用默认值：

```yaml
host: 0.0.0.0
enrollment_token_file: .runbridge/enrollment.token
hub_token_file: .runbridge/hub.token
public_url: http://hub.example:8787  # 改为 Node 和调用方实际可达的 Hub 基址。
```

启动，保留这个终端：

```bash
.venv/bin/runbridge-hub serve --settings hub.yaml
```

另开终端验证：

```bash
curl --fail http://127.0.0.1:8787/health
```

应返回 `{"status":"ok","protocol_version":2}`。将 **Hub 的实际可达基址**（如 `http://hub.example:8787`）和刚生成的 **enrollment.token 文件**私密交给 Node 维护者。独立的 **hub.token** 与 `public_url` 交给调用方，用于查询资源池及领取 Node；申请凭据不交给 Node 进程，也不能直接执行。Node 安装步骤在 Node 项目中；浏览器验证等 Node 接入后进行。

需要 Agent/MCP 时，按[快速开始的 MCP 小节](doc/user-guide/快速开始.md#启用-mcp按需)安装 `[mcp]` 并启用。MCP 客户端在 Hub 本机时，无需配置 `mcp_allowed_hosts`。

启动成功后，点击日志中已附带只读口令的 `Dashboard URL` 即可查看节点总览，刷新页面也可直接进入。日志同时输出口令，支持手动输入；默认文件为数据库同目录的 `.runbridge/web.token`，与登记令牌分开使用。配置、开关及数据含义见[节点总览](doc/user-guide/节点总览.md)。

## 验证一次浏览器操作

调用方从 Hub 领取 Node 并保存 `access.json` 后，可用[标准库 HTTP 示例](doc/reference/examples/执行会话调用.py)完成“打开 Hub 健康页 → 读取页面 → 保存 PNG → 释放会话”。[快速开始](doc/user-guide/快速开始.md#验证一次完整调用node-接入后)使用本部署的健康页，不依赖外部网站；成功时截图显示健康检查 JSON，清理结果为 `COMPLETE`。

任务结束后还需[释放 Node 使用权](doc/reference/Node使用权租约接口.md)，关闭浏览器不会自动释放 Node。默认租期 3600 秒、空闲回收 600 秒，最大租期默认 86400 秒。

Agent 通过 Streamable HTTP 连接 `/mcp`，使用访问文件中的令牌；具体配置见 [MCP 浏览器接入](doc/user-guide/MCP浏览器接入.md)。

## 使用与维护

| 要做的事 | 阅读文档 |
| --- | --- |
| 第一次部署、验证、处理常见错误 | [快速开始](doc/user-guide/快速开始.md) |
| 配置长期运行、交付材料与备份 | [部署与运行](doc/deployment/部署与运行.md) |
| 保存 YAML、查询默认值和适用场景 | [参数详解](doc/reference/参数详解.md)、[带注释 YAML](doc/reference/examples/Hub启动配置.yaml) |
| 编写调用程序、理解对象和请求 ID | [调用方教程](doc/user-guide/调用方对接与使用.md)、[工具调用协议](doc/reference/工具调用协议.md) |
| 配置 DSH-Test-Plugin，通过 Hub MCP 自动化测试 | [DSH-Test-Plugin 对接指南](doc/user-guide/DSH-Test-Plugin对接指南.md) |
| 观察浏览器画面 | [画面流接入](doc/user-guide/浏览器画面流接入.md) |
| 查看全部节点、占用、能力与延迟 | [节点总览](doc/user-guide/节点总览.md) |
| 排查断线、许可、会话与升级问题 | [运行与排障](doc/deployment/运行与排障.md) |

## 开发

源码位于 `src/runbridge_hub/`，使用项目根目录 `.venv`。依赖同步、pytest、构建 wheel 和隔离联调步骤见[本地开发与联调](doc/development/本地开发与联调.md)。

从[代码结构与执行流程](doc/architecture/代码结构与执行流程.md)了解实现，从[文档导航](doc/README.md)查阅当前架构、协议、设计过程和验收记录。报告问题时附上两端版本、已隐藏秘密的配置、错误码和复现步骤；不要提交令牌或私有身份文件。
