# 接口、Web 与 App 执行方案

[文档导航](../README.md) · [平台与执行节点架构](平台与执行节点架构.md)

本文件描述各执行路径及最初的工具 RPC 原型。最新建议优先通过独立节点服务提供原生执行协议，具体见[独立节点服务与对外契约](独立节点服务与对外契约.md)；这里的简化动作接口与 MCP 组合不再是唯一默认接入方式。

## 1. 场景支持矩阵

“可行”表示有对应技术路径，不表示本项目已经实现或完成实测。

| 场景 | 本地组件 | 可行性 | 主要条件 |
| --- | --- | --- | --- |
| 公网/内网 HTTP API | HTTP 执行器、代理、CA、凭据引用 | 高 | 节点可访问目标，允许回传必要响应 |
| 本机启动独立 Chromium | Playwright、本地浏览器 | 高 | 浏览器可启动，版本及运行环境匹配 |
| 复用已登录 Chrome/Edge 页面 | 扩展及本地桥接进程 | 高但需授权 | 扩展允许、用户选择页面、共享状态可接受 |
| Chrome 原生确认后接入当前 Profile | Chrome DevTools MCP 本地进程 | 有条件 | Chrome 144+、用户启用并确认连接；范围较宽 |
| 复用任意未开启控制入口的浏览器 | 无对应授权入口 | 不能保证 | 不能只根据进程存在就接管 |
| Firefox/WebKit 独立测试浏览器 | 本地 Playwright | 可行 | 不沿用 Chromium 扩展/CDP 的接入假设 |
| Android 原生 App/移动 Web | ADB、Appium UiAutomator2 | 高但需准备 | 调试授权、设备在线、驱动/OS 兼容 |
| iOS 常规真机/模拟器 | Mac、Xcode、Appium XCUITest、WDA | 可行，准备较多 | 设备信任、开发者模式、签名及版本匹配 |
| Windows/Linux 控制部分 iOS 真机 | XCUITest 受限路径、RemoteXPC、预装/外部 WDA | 有条件 | 仅适用官方限定环境，需单独验证 |

## 2. 接口测试：请求必须在能够访问目标的节点发出

建议调用链：

> 云端 Agent 生成请求与验证意图 → 本地 HTTP 执行器解析凭据引用 → 本地 DNS/代理/TLS 建连 → 内网接口 → 筛选响应与证据 → 云端分析。

平台保存接口定义、用例、输入数据和验证规则。节点保存本地可用的密钥、证书和必要环境配置；平台命令可以携带 `credential_ref`，由节点替换为真实认证材料，默认不将秘密原值交给模型。

| 情况 | 处理建议 |
| --- | --- |
| 内部域名只能由客户 DNS 解析 | 在节点解析，不能先让云端解析再传 IP |
| 企业 HTTP 代理/VPN | 客户端使用已授权的网络配置，执行前探测目标服务 |
| 私有 CA、mTLS | 配置客户信任链/本地客户端证书，不默认关闭验证 |
| Cookie 登录、OAuth、MFA | 提供对应本地凭据/会话能力；需要人工认证时暂停 |
| 下载文件或大响应 | 本地保存并按允许范围回传摘要/附件，限制大小和目标 |
| 创建、支付、删除等写请求 | 记录业务关联 ID；超时后先查询结果，避免盲目重发 |

HTTPX 等 HTTP 库支持自定义 CA 和客户端证书；这里仅用它证明接口执行器具备常规 TLS 接入路径，实际语言可沿用项目技术栈。[HTTPX SSL 文档](https://www.python-httpx.org/advanced/ssl/)

原生 HTTP 请求不需要经过浏览器页面的跨域读取机制；如果用浏览器 `fetch` 执行接口请求，则仍受页面环境和认证上下文约束。接口执行器与浏览器会话不要默认合并，也不要为了 API 测试自动导出整个浏览器 Cookie 库。

对于敏感系统，可让本地执行器运行预定义、无模型参与的校验，只回传通过/失败及脱敏证据。它能减少数据外发，但云端 Agent 无法据此理解被隐藏的完整业务内容。

## 3. Web 模式 A：独立测试浏览器

**建议作为可重复回归的基础模式。** 客户端用 Playwright 在本机启动独立浏览器或独立持久 Profile；用户可以在该测试 Profile 完成登录，后续复用该 Profile。

这是“复用测试账号登录”，并不等同于“复用此刻日常浏览器中的原始标签页”。产品界面应明确区分，避免用户误以为两个模式具备相同会话状态。

工具 RPC 路径可把 Playwright 调用留在本机。对于保留原生 API 的独立节点服务，优先评估在本地用 `launchServer()` 提供受保护的协议端点，经节点连接转接给调用方 `connect()`；官方要求两端 Playwright 主次版本匹配。CDP 接入仅适用 Chromium，且官方明确其兼容程度低于 Playwright 原生连接。[Playwright BrowserType](https://playwright.dev/docs/api/class-browsertype)

文件上传和下载发生在客户环境，应使用本地授权文件句柄或通过平台下发的测试附件。不要把云端 `/tmp/file.png` 当作客户电脑可读取的路径。驱动结束后只回收本次创建的浏览器和临时目录。

## 4. Web 模式 B：复用用户当前已登录浏览器

### 4.1 优先路径：官方扩展与本地工具服务

已核实，官方 Playwright 扩展允许连接现有 Chrome/Edge/Chromium 页面；首次使用时选择标签页；多个客户端使用独立标签组，单个标签页同时归属于一个客户端。默认连接需要确认，也提供 Profile 专属连接令牌。[固定提交的扩展说明](https://github.com/microsoft/playwright/blob/d9f2fd3e2232ace8e317a84eda6cb86e25bcf49c/packages/extension/README.md)

建议首轮组合：

> 云端 Agent → 云端工具网关 → 节点客户端 → 本地 Playwright MCP `--extension` → 官方扩展 → 用户授权页面。

这条路径把 Agent 留在云端，把 Playwright、扩展桥接和驱动状态留在本机。官方例子描述的是本地连接能力；跨互联网、跨租户的节点接入仍需要平台开发，不能直接把本地 MCP 示例当成完成的 SaaS 产品。

如使用扩展连接令牌，建议只保存在客户节点，按用户明确选择的测试 Profile 使用。该令牌减少扩展连接确认，不替代平台的租户认证、运行授权和本机撤销能力。

准备阶段检查已有页面及业务账号标识，能复用则跳过启动和重复登录；遇到会话失效或 MFA，等待用户处理。测试结束通常解除控制，不关闭用户原有浏览器，不清空其数据。

### 4.2 备选路径：Chrome 原生确认连接

Chrome 144+ 提供启用后确认远程调试连接的方式，Chrome DevTools MCP 可通过 `--autoConnect` 申请接入。当前官方说明指出，连接可以访问所选 Profile 的全部已开窗口；它不是与 Playwright 扩展相同的标签页授权模型。[固定提交的高级用法](https://github.com/ChromeDevTools/chrome-devtools-mcp/blob/f08dbe152502d66e75fa07fb2588dc0feb42bc20/docs/advanced-usage.md)

这条路径适合用户愿意授权整个测试 Profile 的场景，不作为“只授权一个日常页面”的默认替代。也不要据此承诺注册后永久静默连接，具体确认行为需要在目标 Chrome 版本验证。

### 4.3 传统调试端口的边界

Chrome 136 起，传统 `--remote-debugging-port`/`--remote-debugging-pipe` 对默认用户数据目录受限制，需要非默认 `--user-data-dir`。这一限制针对该启动方式，不等于所有现有浏览器复用途径被禁止。[Chrome 官方变更说明](https://developer.chrome.com/blog/remote-debugging-port)

因此，不能把“给用户正在用的默认 Chrome 加上 9222 端口”作为通用产品前提，也不建议复制日常 Profile 到临时目录来规避登录保护。

### 4.4 何时考虑自研扩展和 Relay

如果确实需要自定义页面选择、远程连接和窗口授权，可参考 Playwright 的扩展桥接实现。但扩展 `chrome.debugger` 提供的是受限 CDP 能力，Relay 还需要适配目标、子会话和事件；它不是把 WebSocket 字节直接转发即可完成。[Chrome debugger API](https://developer.chrome.com/docs/extensions/reference/api/debugger)

建议按单页面→新窗口→跨源 iframe/worker→文件和下载逐项验证。分别管理平台控制会话 ID、CDP target/session ID 与本地 tab ID，不能用页面 URL 作为唯一身份。

自研扩展若直接建立 WSS，还要处理 Manifest V3 Service Worker 的生命周期。官方 Chrome 116+ 示例通过在 30 秒活动窗口内交换消息维持连接，示例心跳间隔为 20 秒；还需重连和撤销处理。连接存活不证明网页未冻结或仍可交互。[扩展 WebSocket 生命周期](https://developer.chrome.com/docs/extensions/how-to/web-platform/websockets)

## 5. 已有浏览器复用的行为限制

| 状态或功能 | 建议处理 |
| --- | --- |
| 用户手动导航、关闭标签页、修改表单 | 检测观测变化并重新观察；资源关闭时停止该会话 |
| 同一 Profile 多窗口/多账号 | 识别共享 Cookie 和存储；冲突时独占或使用不同 Profile |
| 新标签页、弹窗、跨源登录跳转 | 明确定义新增资源是否在授权范围；超出范围暂停 |
| 后台、最小化、冻结、被丢弃 | 分别测量操作可用性；通信在线不能证明页面可交互 |
| 文件选择、系统证书/权限对话框 | 单独能力或等待人工处理，不能假定都在 DOM 内 |
| 页面截图与桌面截图 | 优先采集被测页面，不扩大到完整桌面 |
| 停止用例 | 解除本次控制，保留用户原有浏览器；业务写入不自动回滚 |

## 6. Android App 自动化

建议调用链：

> 云端 Agent → 节点 App 工具 → 本机 Appium → UiAutomator2/ADB → 客户 Android 设备。

已核实，UiAutomator2 支持 Windows、Linux、macOS 主机，支持真机、模拟器、原生/混合/移动 Web；当前驱动 5+ 需要 Appium 3，6+ 的 Android 下限为 API 26。应按客户设备版本选择兼容组合，不将所有历史 Appium 2 教程直接用于当前版本。[固定提交的 UiAutomator2 要求](https://github.com/appium/appium-uiautomator2-driver/blob/7a54db007aa8a44f5df21cd0b52afc13c0d277ae/README.md)

用户需要开启 USB 调试并确认电脑 RSA 密钥；官方说明这一确认要由可解锁设备的用户完成。[Android ADB 授权](https://developer.android.com/tools/adb)

客户端登记用户选择的设备、检查授权和在线状态，一台设备初期只运行一个交互用例。通过 Appium 获取 UI 树、截图和动作结果；对于无稳定元素的画布/游戏界面，可评估视觉定位，但不能沿用 DOM 定位假设。

复用现有 App 登录状态时，明确“不清数据、不卸载、不重装”的会话配置并验证实际行为。`noReset` 是驱动配置，不保证业务会话永不过期，也不保证任何场景都不会重启 App。不能为恢复驱动随意清除用户设备数据。

受 `FLAG_SECURE` 保护的窗口可能无法截图；如果视觉 Agent 缺少观测，应使用可用 UI 信息、业务接口验证或明确停止。[Android 安全窗口说明](https://developer.android.com/security/fraud-prevention/activities)

## 7. iOS App 自动化

### 7.1 常规完整路径

推荐先验证：云端 Agent → 客户 Mac 节点 → Appium XCUITest → WebDriverAgent → iPhone/iPad 或模拟器。当前 XCUITest 10+ 需要 Appium 3；设备 OS、驱动/WDA、Xcode 和 macOS 是组合兼容关系，不能只检查有没有 Appium。[系统要求](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/system-requirements/)

真机需要设备信任、Developer Mode 等准备，WDA 需要有效签名和 provisioning profile。签名资产和 Apple 凭据尽量保留在客户环境；安装/更新 WDA 与被测 App 分别作为授权动作。[设备准备](https://appium.github.io/appium-xcuitest-driver/latest/getting-started/device-setup/)

混合 App 的 WebView 还要可调试，不能认为所有已安装 iOS App 的内部网页都能像桌面 Web 一样取得 DOM。系统生物认证和受保护界面也应分别验证。

### 7.2 新版支持的非 Mac 受限路径

本次读取的 XCUITest 官方文档已经说明 Windows/Linux 具有受限支持：仅真机，iOS/tvOS 18+，不自动选择设备，不支持常规 `xcodebuild` 启动 WDA；需要 RemoteXPC，以及预安装 WDA 或外部管理的 WDA。**不能继续断言 iOS 执行一律只能发生在 Mac，也不能宣传任意 Windows 用户接上 iPhone 就能运行。**[非 macOS 主机说明](https://appium.github.io/appium-xcuitest-driver/latest/guides/non-macos-hosts/)

该路径的 WDA 仍需要前置构建/签名/安装安排，解决的是后续运行位置的一部分问题。建议作为独立原型验证项，保留常规 Mac 路径作为首个完整支持目标。

## 8. 工具与观测统一，底层实现分开

平台可以统一“观察、执行动作、验证、记录证据”的接口，但保留 Web、HTTP、App 的不同资源和权限。页面元素引用、手机 UI 节点、坐标和接口响应不是相同类型，错误码和准备状态也不能混用。

需要固定的观察内容、定位可靠性、人工接管方式和业务断言，都应写入每类执行器的能力合同。新增一个驱动并不自动意味着相应场景已经获得产品级支持。
