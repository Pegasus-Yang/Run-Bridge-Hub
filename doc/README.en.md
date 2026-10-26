# Hub documentation

[简体中文](README.md) · English

Current user guides cover **Hub 0.9.3 / Node 0.8.2**. Start with the [README](../README.en.md#quick-start) for source installation or the [quick-start guide](user-guide/快速开始.en.md) for an existing wheel in a separate deployment directory.

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
| Prepare a PyPI distribution | [PyPI release preparation](development/PyPI发布准备.en.md) |
| Contribute and understand licensing | [Contributing](../CONTRIBUTING.en.md), [MIT License](../LICENSE) |
| Develop, validate, and build | [Local development (Chinese)](development/本地开发与联调.md), [packaging (Chinese)](development/版本发布与本地打包.md) |
| Inspect implementation | [Code structure (Chinese)](architecture/代码结构与执行流程.md), [sessions (Chinese)](architecture/Playwright执行与会话管理.md), [MCP lifecycle (Chinese)](architecture/MCP授权与浏览器生命周期.md) |
| Read release changes and manage GitHub presentation | [Release record (Chinese)](project/版本发布记录.md), [GitHub settings (Chinese)](project/GitHub展示配置.md) |
| Follow decisions | [Tool architecture (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/%E5%B7%A5%E5%85%B7%E6%8C%87%E4%BB%A4%E6%89%A7%E8%A1%8C%E6%9E%B6%E6%9E%84%E6%94%B9%E9%80%A0%E6%96%B9%E6%A1%88.md), [protocol draft (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/%E5%B7%A5%E5%85%B7%E8%B0%83%E7%94%A8%E5%8D%8F%E8%AE%AE%E8%8D%89%E6%A1%88.md), [lease design (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/Hub%E7%BB%9F%E4%B8%80%E8%AE%A4%E8%AF%81%E4%B8%8ENode%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%94%B9%E9%80%A0%E6%96%B9%E6%A1%88.md) |
| Inspect recorded acceptance | [Leases (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/Node%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%94%B9%E9%80%A0%E9%AA%8C%E6%94%B6.md), [dashboard (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/%E8%8A%82%E7%82%B9%E6%80%BB%E8%A7%88%E9%A1%B5%E9%9D%A2%E9%AA%8C%E6%94%B6.md), [YAML (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/YAML%E5%90%AF%E5%8A%A8%E4%B8%8E%E5%BF%AB%E9%80%9F%E4%B8%8A%E6%89%8B%E9%AA%8C%E6%94%B6.md), [isolated release (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/Python%E5%B7%A5%E5%85%B7%E6%89%A7%E8%A1%8C%E9%AA%8C%E6%94%B6%E8%AE%B0%E5%BD%95.md), [daily environment (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/%E6%97%A5%E5%B8%B8%E7%8E%AF%E5%A2%83%E5%8D%87%E7%BA%A7%E4%B8%8E%E5%8A%9F%E8%83%BD%E9%AA%8C%E6%94%B6.md) |

Design, architecture, release, and historical evidence remain Chinese. `design/` records decisions; `project/history/` preserves early research. Old SDK tunnels, npm BrowserServer, Hub-side capture, and old acceptance material are not current operating instructions. Dates/status notices take precedence over historical use of "current". Recorded acceptance is not a new live check. Private settings and raw evidence stay in ignored `local/`.

The source distribution includes current user documentation. Historical designs, acceptance records, and raw audit material omitted from it are linked on GitHub.
