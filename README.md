# RunBridge Hub

**通过 HTTP / MCP，让程序和 Agent 使用远程设备上的浏览器。**

简体中文 · [English](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/README.en.md) · [快速开始](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/README.md#%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B) · [完整文档](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/README.md) · [更新日志](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/%E7%89%88%E6%9C%AC%E5%8F%91%E5%B8%83%E8%AE%B0%E5%BD%95.md) · [问题反馈](https://github.com/Pegasus-Yang/Run-Bridge-Hub/issues)

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/pyproject.toml) [![MIT](https://img.shields.io/badge/License-MIT-16a34a?style=flat-square)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/LICENSE)

RunBridge Hub 是 RunBridge 的服务端。它接纳浏览器设备上的 [RunBridge Node](https://github.com/Pegasus-Yang/Run-Bridge-Node)，统一分配设备使用权、管理浏览器会话并转发操作结果。调用方通过 HTTP 或 MCP 使用远程浏览器，无需直接连接 Node 的浏览器端口。

适合自动化程序、Agent 工具接入，以及需要集中分配浏览器设备的测试团队。浏览器、Playwright 和页面对象留在 Node 设备，Hub 自身只需 Python 环境。

## 功能亮点

| 能力 | 可以做什么 |
| --- | --- |
| HTTP 与 MCP 统一入口 | 程序和 Agent 共用认证、会话与执行流程 |
| 跨设备浏览器操作 | Node 主动连接 Hub，调用方经由统一入口使用设备 |
| Node 独占租约 | 领取、续租和释放整个 Node，到期或闲置后回收，避免任务抢占同一设备 |
| 可查询的执行结果 | 按请求 ID 去重并查询原结果，处理超时和断线，避免重复提交动作 |
| 页面画面流 | 转发 Node 采集的同一页面画面，观察远程执行过程 |
| 只读节点总览 | 搜索和筛选节点，查看连接、资源占用、支持能力、心跳与实测控制通道 RTT |

## 实际效果

节点总览将设备连接、资源占用和能力放在同一页面，支持桌面与手机。点击节点可查看详情；总览使用独立只读口令。

![RunBridge Hub 节点总览：在线状态、资源占用、支持能力与实测 RTT](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/assets/node-dashboard/%E5%A4%A9%E8%93%9D%E4%B8%BB%E9%A2%98%E6%A1%8C%E9%9D%A2.jpg?raw=true)

截图来自本地验收场景，展示当时的数据。运行后的总览显示所连接 Hub 的实际状态；字段含义见[节点总览指南](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%8A%82%E7%82%B9%E6%80%BB%E8%A7%88.md)。

## 工作方式

![RunBridge Hub 架构与执行方式](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/architecture/assets/hub-overview.svg?raw=true)

Hub 与 Node 分别部署：Hub 提供服务入口，Node 在浏览器所在设备执行。两者的配置、身份与运行环境各自独立。

## 快速开始

Hub **0.9.3** 已发布至 [PyPI](https://pypi.org/project/runbridge-hub/0.9.3/)，可按下方命令安装。也可从 [GitHub Releases](https://github.com/Pegasus-Yang/Run-Bridge-Hub/releases) 下载安装包，再按[独立目录安装指南](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md)部署，或使用源码安装路线。

### 从 PyPI 安装

准备 Python 3.14 与 uv，在新的部署目录执行。选择本方式后直接继续第 2 步；仅使用 HTTP 时可去掉 `[mcp]`。

镜像同步可能晚于首次发布。若下方阿里云镜像尚未提供此版本，可从 [PyPI 文件列表](https://pypi.org/project/runbridge-hub/0.9.3/#files)下载 wheel，按独立目录安装指南安装。

```bash
mkdir -p ~/runbridge-hub
cd ~/runbridge-hub
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python "runbridge-hub[mcp]==0.9.3" -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/runbridge-hub generate-token --output .runbridge/enrollment.token
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

### 1. 安装 Hub

在 **Hub 机器**准备 Git、Python **3.14.x** 和 [uv](https://docs.astral.sh/uv/getting-started/installation/)。以下命令使用 macOS / Linux shell：

```bash
git clone https://github.com/Pegasus-Yang/Run-Bridge-Hub.git
cd Run-Bridge-Hub
uv sync --locked --no-dev -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/runbridge-hub generate-token --output .runbridge/enrollment.token
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

`uv` 在仓库根目录创建 `.venv`。两份凭据分别供 **Node 登记**和**调用方领取 Node**使用。已有 wheel 的独立目录安装方法见[部署与运行](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/deployment/%E9%83%A8%E7%BD%B2%E4%B8%8E%E8%BF%90%E8%A1%8C.md)。

### 2. 保存配置并启动

在当前安装目录创建 `hub.yaml`，将 `public_url` 换成 **Node 与调用方实际可达的 Hub 基址**：

```yaml
host: 0.0.0.0
enrollment_token_file: .runbridge/enrollment.token
hub_token_file: .runbridge/hub.token
public_url: http://hub.example:8787
```

```bash
.venv/bin/runbridge-hub serve --settings hub.yaml
```

保留此终端，另开终端检查：

```bash
curl --fail http://127.0.0.1:8787/health
```

预期返回 `{"status":"ok","protocol_version":2}`。点击启动日志的 `Dashboard URL` 可打开节点总览；尚未登记设备时列表为空。凭据文件和包含只读口令的总览链接应妥善保管。

源码安装可按需补充 MCP 可选依赖；上面的 PyPI 命令已经包含此 extra：

```bash
uv sync --locked --no-dev --extra mcp -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

在 `hub.yaml` 增加 `mcp_enabled: true` 后重启。Agent 使用 Streamable HTTP 连接实际 Hub 基址后的 `/mcp`；连接参数与调用步骤见 [MCP 接入](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/MCP%E6%B5%8F%E8%A7%88%E5%99%A8%E6%8E%A5%E5%85%A5.md)。

### 3. 接入 Node，验证浏览器操作

将 Hub 基址与真实 `enrollment.token` 私密交给设备维护者，按 [Node 快速开始](https://github.com/Pegasus-Yang/Run-Bridge-Node#快速开始)上线设备。另向调用方提供独立 `hub.token`，按[调用方教程](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%B0%83%E7%94%A8%E6%96%B9%E5%AF%B9%E6%8E%A5%E4%B8%8E%E4%BD%BF%E7%94%A8.md)领取 Node，保存返回的 `.runbridge/access.json`。

源码安装已经包含示例。PyPI 或 wheel 安装请先在部署目录按相同路径下载两份标准库脚本：

```bash
mkdir -p doc/reference/examples
curl --fail --location https://raw.githubusercontent.com/Pegasus-Yang/Run-Bridge-Hub/main/doc/reference/examples/%E6%89%A7%E8%A1%8C%E4%BC%9A%E8%AF%9D%E8%B0%83%E7%94%A8.py --output doc/reference/examples/执行会话调用.py
curl --fail --location https://raw.githubusercontent.com/Pegasus-Yang/Run-Bridge-Hub/main/doc/reference/examples/node_lease.py --output doc/reference/examples/node_lease.py
```

运行示例，打开网页、读取标题、保存 PNG、关闭会话并交还 Node：

```bash
.venv/bin/python doc/reference/examples/执行会话调用.py --access-file .runbridge/access.json --resource-id chromium --url https://example.com --screenshot .runbridge/page.png
.venv/bin/python doc/reference/examples/node_lease.py release --access-file .runbridge/access.json
```

资源 ID 使用 Node 实际上报的值，目标网页需由 **Node 设备**访问。核对截图内容、`cleanup=COMPLETE` 与租约 `RELEASED`。完整步骤与不依赖外部网站的示例见[快速开始](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md)。

## 支持范围

- 当前 Hub **0.9.3**，配套 Node **0.8.2**，需要 Python **3.14.x**；Hub 无需安装浏览器、Playwright 或 Node.js。
- 提供 **33 项项目方法、27 个 MCP 工具**。调用方式借鉴 Playwright，具体支持以[方法表](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/Playwright%E6%96%B9%E6%B3%95%E8%A1%A8.md)为准；官方 SDK 直连、任意脚本和 SDK 回调不在当前范围内。
- managed 浏览器支持 HTTP / MCP，borrowed Chrome 通过 HTTP 使用；页面画面用于观察，业务结果由调用方验证。
- 浏览器会话与 Node 租约分别释放。关闭浏览器后，整批任务结束还需交还 Node；清理未知时保持隔离，见[租约接口](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/Node%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%8E%A5%E5%8F%A3.md)。

## 文档与帮助

| 从这里开始 | 内容 |
| --- | --- |
| [完整文档导航](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/README.md) | 按部署者、调用方和维护者划分的阅读路线，含英文入口 |
| [快速开始](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.md) · [部署与运行](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/deployment/%E9%83%A8%E7%BD%B2%E4%B8%8E%E8%BF%90%E8%A1%8C.md) | 安装、配置、启动、验证、交付和备份 |
| [参数详解](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/%E5%8F%82%E6%95%B0%E8%AF%A6%E8%A7%A3.md) · [注释 YAML](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/examples/Hub%E5%90%AF%E5%8A%A8%E9%85%8D%E7%BD%AE.yaml) | 参数、默认值、路径规则与使用场景 |
| [调用方教程](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%B0%83%E7%94%A8%E6%96%B9%E5%AF%B9%E6%8E%A5%E4%B8%8E%E4%BD%BF%E7%94%A8.md) · [租约接口](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/Node%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%8E%A5%E5%8F%A3.md) | 领取设备、操作页面、查询结果和交还资源 |
| [MCP 接入](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/MCP%E6%B5%8F%E8%A7%88%E5%99%A8%E6%8E%A5%E5%85%A5.md) · [DSH 插件对接](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/DSH-Test-Plugin%E5%AF%B9%E6%8E%A5%E6%8C%87%E5%8D%97.md) | Agent 工具、插件配置与整批任务生命周期 |
| [页面画面](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E6%B5%8F%E8%A7%88%E5%99%A8%E7%94%BB%E9%9D%A2%E6%B5%81%E6%8E%A5%E5%85%A5.md) · [节点总览](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%8A%82%E7%82%B9%E6%80%BB%E8%A7%88.md) | 观察页面和设备状态 |
| [运行与排障](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/deployment/%E8%BF%90%E8%A1%8C%E4%B8%8E%E6%8E%92%E9%9A%9C.md) | 常见错误、升级、清理未知和离线核查 |

## 开发与贡献

欢迎通过 [Issues](https://github.com/Pegasus-Yang/Run-Bridge-Hub/issues) 反馈或提交 Pull Request。请附上两端版本、运行环境、复现步骤和已隐藏秘密的错误信息。

源码开发使用根目录 `.venv`，依赖同步、pytest 与隔离联调见[本地开发与联调](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/development/%E6%9C%AC%E5%9C%B0%E5%BC%80%E5%8F%91%E4%B8%8E%E8%81%94%E8%B0%83.md)；提交范围与验证要求见[贡献指南](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/CONTRIBUTING.md)。项目由 [Pegasus-Yang（天马）](https://github.com/Pegasus-Yang)维护。

## 许可证

本项目采用 [MIT License](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/LICENSE)。随 Hub 分发的 [Phosphor Icons](https://github.com/phosphor-icons/core) 保留其[原始 MIT 许可证](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/src/runbridge_hub/web/icons/LICENSE)与版权声明，其他第三方依赖遵循各自的许可证。
