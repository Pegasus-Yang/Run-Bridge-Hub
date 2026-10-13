# 运行与排障

[文档导航](../README.md) · [安装](安装与运行.md) · [跨机器网络与字体](跨机器部署与中文字体.md) · [调用方指南](../user-guide/调用方对接与使用.md)

适用于 0.4.0。按 Hub → Node → 资源 → 会话 → 原生 SDK → 画面顺序定位，先读取真实状态，再决定是否重启或重新申请。查询接口、执行接口和画面接口分别处理，不把一个通道连通当作所有功能正常。

## 1. 最小诊断信息

| 检查 | 命令或字段 | 判断 |
| --- | --- | --- |
| Hub 健康 | curl --fail http://实际Hub地址/health | 服务是否已经初始化 |
| Node 查询 | inspect node_example --access-file ... | ONLINE、连接代次、capabilities_stale |
| 本机资源 | capabilities.resources | 对应 ID、READY/FREE、backend 与版本 |
| 会话查询 | session get session_example --access-file ... | state、expires_at、cleanup、close_reason/error_code |
| SDK | 官方异常与实际 DOM/业务状态 | 动作是否生效、是否业务正确 |
| 画面 | visual.state/reason_code/selection/frame_age_ms | 能力声明、首帧、选择、陈旧或错误 |

源码 CLI 前缀为 uv run --locked --no-sync runbridge-node，wheel 为 .venv/bin/runbridge-node。替换实际 ID/配置路径，令牌只从私有访问文件读取。只记录公开错误码、版本、模式和状态，不粘贴完整身份、浏览器端点、Cookie 或握手原文。

## 2. 安装与服务连接

| 症状 | 检查与处理 |
| --- | --- |
| uv 不能写全局缓存 | 对本次命令设置 UV_CACHE_DIR 为当前项目可写目录，例如 UV_CACHE_DIR=.uv-cache uv sync ...；保留原锁定和镜像参数 |
| Python 版本拒绝 | 项目要求标准 3.14.x；在本项目根目录用 uv 创建/同步 .venv |
| 命令不存在 | 源码先 uv sync，再 uv run --locked --no-sync；wheel 用对应 .venv/bin 下的 CLI |
| Hub 缺登记凭据 | 明确提供 --enrollment-token-file，或部署方环境中的 RUNBRIDGE_ENROLLMENT_TOKEN |
| Hub health 不通 | 检查监听地址/端口、工作目录、网桥、防火墙和代理；虚拟机 127.0.0.1 不指宿主机 |
| INVALID_ENROLLMENT_TOKEN | 登记文件必须属于当前 Hub，不用调用许可或 Node 身份代替 |
| INVALID_NODE_TOKEN / NODE_IDENTITY_CONFLICT | 核对原节点身份与 Hub，保留已有 node.json，不通过删文件反复登记修复 |
| Node 被同身份连接替换 | 保留一个常驻进程；同身份新连接会替换旧进程，旧进程按设计退出 |
| Node 在线但没有浏览器资源 | run 必须带 --chrome-config 或 --playwright-config 之一；仅控制模式没有执行资源 |

文件生成/签发命令拒绝覆盖。换一个输出文件名或使用原有效文件，不为了重复执行命令清空身份。标准代理/证书行为和临时局域网绕过方式见跨机器指南，生产不通过关闭证书验证解决 TLS 问题。

## 3. 已有 Chrome 模式

| 症状/码 | 检查与处理 |
| --- | --- |
| CHROME_CONNECT_FAILED / UNAVAILABLE | 浏览器是否仍在运行，本地固定 ws 端点是否可达；确认是 browser 级入口、BROWSER_INSTANCE |
| 配置被拒绝 | 只接受明确授权的本机回环浏览器级 ws；不使用 HTTP 自动发现、page 端点或远程地址 |
| Chrome 重启后仍不可用 | 浏览器 ID 已改变；所有者重新确认端点、保存新配置并重启 Node，不自动换绑 |
| CDP_CLIENT_VERSION_UNSUPPORTED | SDK 至少 1.60；指南用已验收 1.63.0，并设置 no_defaults=True |
| 找不到原页面 | 用已有 context/pages；确认 URL 是实际已打开值且唯一，重复恢复的测试标签页应由所有者核对 |
| 页面动作等待稳定超时 | 检查页面可见性、实际 DOM 与浏览器后台状态；自己的测试页可先 bring_to_front，不能默认当作业务失败 |
| RUNBRIDGE_BORROWED_BROWSER_COMMAND_FORBIDDEN | 本模式拒绝退出/崩溃整个浏览器及旧式不透明封装；使用 SDK browser.close() 释放连接 |

借用模式只清理自己的连接、采集进程和临时目录，没有浏览器 PID/Profile 所有权。不要按受管理模式的自建进程记录去清理用户 Chrome。

## 4. 受管理 Chromium 模式

| 症状/码 | 检查与处理 |
| --- | --- |
| RESOURCE_NOT_READY / UNAVAILABLE | Node.js/npm、私有运行时/Chromium 缓存、启动配置与本机库是否完整 |
| prepare-playwright 拒绝目录 | 该目录包含不同锁文件；使用独立目录，不清理共享 node_modules/cache |
| PLAYWRIGHT_START_FAILED | 先用 headless=true 的最小配置，核对 Node.js 路径、launch_options 字段和系统依赖 |
| PLAYWRIGHT_VERSION_MISMATCH | 官方 SDK 与 npm Playwright 主、次版本一致；当前先维持 1.63.0 |
| timeout 调大仍准备超时 | 工具 timeout 为毫秒，但外层准备最多 30 秒；不能通过设置 0 取消外层限制 |
| cleanup UNKNOWN | 查看本模式运行时目录的 cleanup-unknown-node_id.json，核对记录的自建 PID/进程组和专用 temporary_directory |

清理未知标记须由所有者确认对应自建进程已退出、专用目录已处理后再移除并重启 Node。禁止泛化为清理全部 Chrome 进程或用户 Profile。本模式完整验收为 macOS arm64；借用 Chrome 的 Ubuntu 验收不等于本模式的 Linux 验收。

## 5. 许可、会话与资源占用

| 错误/状态 | 下一步 |
| --- | --- |
| 401 INVALID_ACCESS_TOKEN | 许可缺失、错误、到期或撤销；由所有者签发新文件，不改旧 JSON 期限 |
| RESOURCE_OUTSIDE_GRANT | 许可没有覆盖该资源 ID，按真实范围重新签发 |
| SESSION_OUTSIDE_GRANT | 使用创建该会话的同一许可；新许可不能接管旧会话 |
| RESOURCE_BUSY | 当前会话、预约或未知清理仍占用；查询状态，不重复申请抢占 |
| SESSION_NOT_CONNECTABLE | 会话已经接入/结束，或不是 READY；一个会话只允许一条原生调用连接 |
| NATIVE_PROTOCOL_MISMATCH | 按 native_protocol 使用返回的对应入口 |
| UNSUPPORTED_NATIVE_QUERY | 不给原生 URL 拼 token、额外查询参数或不支持的控制选项 |
| CLOSED / INTERRUPTED | SDK 对象已失效；先核查实际业务效果，再申请新会话 |
| cleanup PENDING / UNKNOWN | 不是确认完成；检查 Node 报告和模式对应的清理证据 |

READY 会话也受租期约束，即使从未接入 SDK。正常结束不回滚已经生效的页面动作；执行网络错误可能发生在动作之后，不自动重放 POST、点击或提交。

## 6. 画面与中文

| 症状 | 下一步 |
| --- | --- |
| supported=true 但 streams=[] | 无当前许可创建的 ACTIVE 会话；保持原生执行连接再查询 |
| visual 缺失 | 旧 Hub/查询合同，按实际版本检查；新客户端允许缺省，旧严格模型需升级 |
| UNSUPPORTED_BACKEND | 受管理模式当前没有独立画面流；已有 Chrome 才支持本扩展 |
| WAITING_TARGET | 多页或目标关闭，查询 targets 并选择；切换不激活业务页 |
| TARGET_SELECTION_PENDING | 前一个选择尚未完成；等待 APPLIED/FAILED，不重复并发 PUT |
| VISUAL_TARGET_NOT_FOUND | 使用当前查询返回的目标 ID，列表可能刚更新 |
| 202 但无图 | 受理不等于成功，等待 selection.state=APPLIED 与 LIVE；10 秒超时读取错误原因 |
| FRAME_STALE / ERROR | 清空旧图，检查采集、浏览器与网络，不将旧缓存当作实时画面 |
| FRAME_TOO_LARGE | 原 PNG 超过 4 MiB；本期不自动缩放，所有者调整页面/视口后重试 |
| 图片解码失败 | 先移除 4 字节长度和 JSON；整个二进制消息不是裸 PNG |
| ERR_BLOCKED_BY_LOCAL_NETWORK_ACCESS_CHECKS | 页面来源被浏览器局域网访问策略拦截；本地演示使用回环 HTTP 来源，再核对实际权限，不关闭安全检查 |
| 前端 fetch 跨域失败 | Hub 没有配置 CORS；平台需同源代理/明确跨域设计，HTML 示例只使用 WS |
| 中文显示方框 | 字体装在 Node 浏览器用户下，刷新缓存并由所有者重启浏览器；再确认新 CDP 端点 |

完整操作见[画面指南](../user-guide/浏览器画面流接入.md)和[中文字体](跨机器部署与中文字体.md)。订阅断开不影响原生执行；原生会话结束会关闭上传、采集和订阅。截图、连接或 cleanup 不是业务成功判定。

## 7. 输出、重启与构建

调用方 screenshot、download.save_as()、tracing.stop(path=...) 保存到调用机器；Node 本地自定义输出目录按工具语义保留。download.path() 在原生远程模式不提供远端本机路径。

升级前一致性备份 SQLite 和身份，v2 数据库不能交给 0.1.0 程序直接回退。Hub 重启使旧会话中断，Node 重连后重新报告，调用方用新会话；不恢复或重放旧 SDK 对象。固定单 Worker，原生消息上限 16 MiB、库接收队列 4；升级 Uvicorn/websockets 时复核握手、背压与关闭行为。

各自源码项目的构建命令：

```bash
uv build -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

wheel 必须包含对应 src 包，Node 还包含 server.mjs/package.json/package-lock.json；浏览器 cache/node_modules 不分发，受管理部署仍需准备运行时。文档和完整示例位于 sdist 的 doc，wheel 安装者从配套源码或文档包取得。

当前支持证据是[0.4.0 画面验收](../project/浏览器画面流验收记录.md)、[特定 Ubuntu ARM64 跨机器与字体实测](../project/虚拟机Node跨机器验收记录.md)以及历史受管理验收；公网 TLS/代理、Windows、锁屏和持续容量未形成结论。
