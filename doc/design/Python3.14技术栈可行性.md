# RunBridge 的 Python 3.14 技术栈可行性

[文档导航](../README.md) · [依赖核验记录](../reference/Python依赖核验记录.json)

## 1. 判断

**Python 3.14 + Pydantic V2 可以实现 RunBridge Hub 的节点管理与连接网关，以及 RunBridge Node 客户端。** asyncio 适合网络连接、状态协调和子进程管理；Pydantic 适合控制消息、配置与查询数据。Pydantic 本身不提供网络服务器、任务调度或持久化。

用户已确认将标准 CPython 3.14.x、Pydantic V2 与 asyncio 作为首期技术基线；依赖快照不因此成为已验证的锁文件，完整组合仍按 R0 阶段安装、锁定和验证。

官方 Pydantic 2.12 已引入 Python 3.14 支持，V1 的 Python 支持上限为 3.13。新项目使用 V2 API，不引入 `pydantic.v1` 兼容路线。[Pydantic 官方说明](https://pydantic.dev/articles/pydantic-v2-12-release)

FastAPI 官方发布记录也明确加入 Python 3.14 支持。[FastAPI 发布记录](https://fastapi.tiangolo.com/release-notes/)

原研究结论基于公开支持与分发能力。当前 R0/R1 的基础组合已在 Python 3.14.7 下安装、导入、构建并通过双端连接验收，精确版本见[运行核验记录](../reference/R0与R1运行核验记录.json)；受管理 Chromium 与 R4 Chrome 复用已有专项验收，见[R4 记录](../project/R4Chrome复用验收记录.md)；手机组合仍未运行。

## 2. 发布元数据快照

2026-10-11 从 PyPI 官方接口读取如下快照，完整依赖和 wheel 文件名保存在核验记录。

| 包 | 读取版本 | Python 3.14 证据 | 当前角色 |
| --- | --- | --- | --- |
| Pydantic | 2.14.0 | 官方支持说明、3.14 classifier、通用 wheel | 控制面模型和配置 |
| pydantic-core | 2.50.0 | 3.14 classifier、标准 cp314 wheel | Pydantic 锁定的原生依赖 |
| FastAPI | 0.143.0 | 官方发布说明、3.14 classifier | 管理 HTTP API |
| Starlette | 1.7.0 | 3.14 classifier、通用 wheel | FastAPI 的 ASGI/WebSocket 基础 |
| Uvicorn | 0.54.0 | 3.14 classifier、通用 wheel | 服务器运行 |
| websockets | 17.2 | 3.14 classifier、标准 cp314 及通用 wheel | 客户端出站连接、网关本地转接 |
| HTTPX | 0.28.1 | Requires-Python 允许 3.14、通用 wheel；未显式列 3.14 | HTTP 请求与代理的候选，需补运行验证 |
| aiosqlite | 0.22.1 | Requires-Python 允许 3.14、通用 wheel；未显式列 3.14 | SQLite 异步访问的可选便利库 |
| Playwright Python | 1.63.0 | 3.14 classifier、平台 wheel | Python 调用方/可选本地适配 |
| greenlet | 3.5.6 | 3.14 classifier、标准 cp314 wheel | Playwright Python 的原生依赖 |
| Appium Python Client | 6.0.7 | 3.14 classifier、通用 wheel | Python 调用方的可选 SDK |
| Selenium | 4.51.0 | 3.14 classifier、通用 wheel | Appium Python Client 依赖 |

pydantic-core、websockets 和 greenlet 的标准 cp314 wheel 覆盖本次检查的 macOS arm64、Windows x86_64、Linux x86_64。这里只确认 wheel 分发存在，不据此宣称这些平台的设备驱动或完整运行组合均已通过。

Requires-Python 不排除 3.14、通用 wheel 存在，是可安装候选的证据，弱于明确的 3.14 支持声明。原元数据检查不表示 HTTPX/aiosqlite 已实测兼容；当前基础组合已安装并通过 R1 HTTP/SQLite 场景验证，仍不能仅凭 classifier 判定后续驱动组合可运行。

这些是研究快照，不是最终锁文件。实施前用 uv 解析并锁定完整依赖，核对原生 wheel 和目标操作系统，再运行最小连接/执行验证。

## 3. 为什么优先使用标准 CPython

推荐标准 CPython 3.14.x 和标准 asyncio，首期不依赖 free-threaded 构建或 JIT 获取性能。连接代理主要是 I/O，必要的外部工具以子进程运行。无需为了选用 3.14 同时增加新的并发运行模式。

Python 3.14 的 asyncio 和 sqlite3 都有标准库支持。[asyncio](https://docs.python.org/3.14/library/asyncio.html)、[sqlite3](https://docs.python.org/3.14/library/sqlite3.html)

当前本地可读到标准 CPython 3.14.7，但此事实只说明解释器已存在，原研究没有验证依赖安装；当前已为 Hub 与 Node 分别创建根目录 .venv 并完成基础运行验证。

## 4. Pydantic 放在哪里

| 数据 | 建议处理 |
| --- | --- |
| 节点登记、访问许可、查询、会话控制、配置 | 明确的 Pydantic V2 模型和协议版本 |
| 本服务拥有的字段 | 明确允许/拒绝额外字段，避免拼错字段悄悄生效 |
| 后端特有配置和扩展能力 | 保留扩展结构，注明版本及解释方 |
| Playwright 原生帧、Appium 原生请求/响应 | 保留内容和语义，不逐 API 复制成自有 Pydantic 模型 |

Pydantic 默认会忽略额外字段。若把 Appium capabilities 或原生工具参数套进默认模型，可能静默丢失扩展参数。因此控制面与原生执行载荷分开验证；Pydantic 不负责缩减执行工具能力。[Pydantic extra 配置](https://pydantic.dev/docs/validation/latest/api/pydantic/config/)

## 5. Python 服务仍需要外部工具运行时

### Playwright 原生服务

Playwright Python 的 `connect()` 可以连接由 Node.js `launchServer()` 创建的浏览器服务；官方要求双方主次版本匹配。不能把 Node.js 的 `launchServer()` 当作 Python 公开 API 的同名方法。[Playwright Python BrowserType](https://playwright.dev/python/docs/api/class-browsertype)

当前 PyPI Playwright 为 1.63.0，npm latest 为 1.64.0，二者不能仅按各自 latest 安装后假定兼容。本次另外确认 npm 1.63.0 发布存在，可以将双方 1.63.0 作为后续验证候选；没有运行该组合。

建议节点 Python 客户端负责生命周期和网关连接，配套 Node.js Playwright 服务负责原生浏览器端点。不自行从 Python 重实现 Playwright 私有协议。只需要本地动作适配时也可使用 Python Playwright，但不能把该路线宣传成原生 API 的透明完整替代。

### Appium 服务

Appium server 本身基于 Node.js。当前官方要求 Node.js `^20.19.0 || ^22.12.0 || >=24.0.0`、npm >=10；本次 registry 的 Appium 为 3.8.0。[Appium 系统要求](https://appium.io/docs/en/latest/quickstart/requirements/)

Python 客户端可管理 Appium 进程并代理其 HTTP 接口。服务器/网关不需要为转发 Appium 协议而安装完整 Selenium/Appium Python SDK；只有实际使用 SDK 的调用方或适配器需要它们。

Android 还需要 ADB、SDK 和驱动；iOS 取决于 XCUITest/WDA、设备准备和所选主机路径。这些不能由 Pydantic 或解释器升级代替。

## 6. 推荐依赖边界

| 位置 | 首期基础 | 按需要安装 |
| --- | --- | --- |
| RunBridge Hub | Python 3.14、Pydantic V2、FastAPI/Uvicorn、WebSocket 支持、sqlite3 | HTTPX、SQLite 异步便利库 |
| RunBridge Node | Python 3.14、Pydantic V2、asyncio、websockets | HTTPX、Playwright Python 等实际适配所需库 |
| 执行子进程 | 与已声明能力匹配的工具及运行时 | Node.js Playwright/Appium、浏览器、ADB/WDA |

Uvicorn 支持不同 WebSocket 实现。首期使用已锁定并验证的实现；标准 asyncio 足够，不强制额外引入 uvloop/httptools 等性能依赖。[Uvicorn 配置](https://uvicorn.dev/settings/)

Python 环境按项目约定使用 uv 和项目根 `.venv/`。依赖安装遵循指定镜像；原研究只读取公开元数据，当前基础运行依赖已安装并写入各自 uv.lock。

## 7. 尚待验证

基础依赖解析、V2 控制模型与 ASGI/WebSocket 本机组合已在 R0/R1 通过。尚待验证远程 TLS 和代理部署、跨平台运行、浏览器原生服务、Appium/设备操作及客户端分发。本次可以确认技术栈具备公开支持与实现基础，不能宣称生产稳定性或完整工具覆盖已验证。
