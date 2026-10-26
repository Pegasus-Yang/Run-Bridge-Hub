# Hub documentation

[简体中文](README.md) · English

Current user guides cover **Hub 0.9.2 / Node 0.8.1**. Start with the [README](../README.en.md#quick-start) for source installation or the [quick-start guide](user-guide/快速开始.en.md) for an existing wheel in a separate deployment directory.

## Choose your reading path

| Role | Path |
| --- | --- |
| Hub deployer | Quick start → deployment → parameters/credentials → dashboard → operations |
| Program or agent client | Client guide → Node lease → HTTP methods or MCP → frames and cleanup |
| DSH user | DSH integration → MCP → batch lease and release |

## User guides, deployment, and interfaces

| Goal | English guide |
| --- | --- |
| Install, start, and verify | [Quick start](user-guide/快速开始.en.md) |
| Deploy separately, hand off, and back up | [Deployment](deployment/部署与运行.en.md) |
| Look up options and defaults | [Parameters](reference/参数详解.en.md), [annotated YAML](reference/examples/Hub启动配置.en.yaml) |
| Distinguish configuration and credential roles | [Configuration and credentials](reference/部署配置与凭据.en.md) |
| Write a client and complete an operation | [Client guide](user-guide/调用方对接与使用.en.md), [examples](reference/examples/README.en.md) |
| Claim, renew, and return Node | [Node lease API](reference/Node使用权租约接口.en.md) |
| Understand requests, objects, and results | [Tool protocol](reference/工具调用协议.en.md), [Playwright methods](reference/Playwright方法表.en.md) |
| Connect an agent | [MCP integration](user-guide/MCP浏览器接入.en.md) |
| Run DSH automated tests | [DSH-Test-Plugin integration](user-guide/DSH-Test-Plugin对接指南.en.md) |
| Observe the operated page | [Streaming guide](user-guide/浏览器画面流接入.en.md), [visual contract](reference/浏览器画面流接口.en.md) |
| Inspect devices, occupancy, and RTT | [Dashboard](user-guide/节点总览.en.md) |
| Diagnose errors, upgrade, or review unknown cleanup | [Operations and troubleshooting](deployment/运行与排障.en.md) |
| Check runtime requirements and supported scope | [Dependencies and scope](reference/当前依赖与实现边界.en.md) |

Each guide links to its Chinese counterpart. Dashboard labels, some CLI output, and shared example messages remain Chinese. English text does not change runtime locale or browser defaults.

## Development and historical material

| Goal | Resource |
| --- | --- |
| Contribute and understand licensing | [Contributing](../CONTRIBUTING.en.md), [MIT License](../LICENSE) |
| Develop, validate, and build | [Local development (Chinese)](development/本地开发与联调.md), [packaging (Chinese)](development/版本发布与本地打包.md) |
| Inspect implementation | [Code structure (Chinese)](architecture/代码结构与执行流程.md), [sessions (Chinese)](architecture/Playwright执行与会话管理.md), [MCP lifecycle (Chinese)](architecture/MCP授权与浏览器生命周期.md) |
| Read release changes and manage GitHub presentation | [Release record (Chinese)](project/版本发布记录.md), [GitHub settings (Chinese)](project/GitHub展示配置.md) |
| Follow decisions | [Tool architecture (Chinese)](design/工具指令执行架构改造方案.md), [protocol draft (Chinese)](design/工具调用协议草案.md), [lease design (Chinese)](design/Hub统一认证与Node使用权租约改造方案.md) |
| Inspect recorded acceptance | [Leases (Chinese)](project/Node使用权租约改造验收.md), [dashboard (Chinese)](design/节点总览页面验收.md), [YAML (Chinese)](project/YAML启动与快速上手验收.md), [isolated release (Chinese)](project/Python工具执行验收记录.md), [daily environment (Chinese)](project/日常环境升级与功能验收.md) |

Design, architecture, release, and historical evidence remain Chinese. `design/` records decisions; `project/history/` preserves early research. Old SDK tunnels, npm BrowserServer, Hub-side capture, and old acceptance material are not current operating instructions. Dates/status notices take precedence over historical use of "current". Recorded acceptance is not a new live check. Private settings and raw evidence stay in ignored `local/`.
