> 历史验收记录：仅证明原记录版本及当时环境，不代表 0.6.0 的当前部署。现行手册见[文档导航](../README.md)。

# RunBridge Playwright 阶段验收记录

[文档导航](../README.md) · [当前架构](../architecture/Playwright执行与会话管理.md) · [完整调用](../user-guide/调用方对接与使用.md)

验收时间：2026-10-11T23:28:50.423014+08:00。版本：0.2.0。结果：**通过当前阶段验收**，R0/R1 保持可用，R2 资源/会话与 R3 受管理 Chromium 原生执行已完成。

## 已核验事实

| 项目 | 结果 |
| --- | --- |
| Python / 平台 | 标准 CPython 3.14.7、GIL 开启、macOS 26.6.2 arm64，两项目各自 .venv |
| Playwright / 浏览器 | Python/npm 1.63.0；Node.js 25.6.1；Chromium 153.0.8010.12 |
| Hub / 存储 | 单 ASGI Worker、asyncio、SQLite v2、内存路由，无 Redis |
| 全量测试 | Hub 20 + Node 16 = **36 项通过，0 失败、0 错误、0 跳过** |
| 实际进程证据 | 9 个记录：R1 三个场景、原生 SDK、清理、撤销/到期、重启、示例与 helper 崩溃 |
| 事件与方法 | Browser/Context/Page/Locator、dialog/popup、route 回调、TimeoutError 原样 |
| 输出 | PNG 1449342 字节；上传/下载各 262144 字节并核对内容；Trace ZIP |
| 转发合同 | 模拟节点 ASGI 测试保留 2097152 字节二进制、文本类型、顺序与未知原生字段 |
| 授权与占用 | 错误许可/其他许可/版本被拒绝，PREPARING 和 ACTIVE 的资源冲突明确 |
| 生命周期 | 撤销、未接入租期、正常/异常 Hub 重启、旧对象失效、不重放、清理未知隔离 |
| 完整调用示例 | examples/playwright_smoke.py 与指南 Python 代码块都实际执行并确认释放 |
| 异常进程清理 | helper 被强制结束后，其自建 Chromium 独立进程组和专用临时目录被回收 |

精确测试名称、实际版本、输出摘要与源码/示例哈希见[运行核验记录](../reference/Playwright运行核验记录.json)。wheel/sdist 和安装检查单独记录在[构建核验](../reference/构建产物核验记录.json)，避免把静态打包检查混同浏览器执行证据。

## 明确边界

当前每个 Node 一个受管理 Chromium 资源位、每会话一条官方 SDK 连接。启动参数由本机所有者配置，执行参数、对象、回调和原生方法错误由官方 SDK/协议处理，不承诺逐项覆盖所有 Playwright API。

真实测试在同一台 macOS 上通过回环网络进行，已验证本机浏览器访问节点侧 HTTP 示例服务；这不能证明隔离网络、远程 TLS/NAT 或其他操作系统的部署已经通过。100 用户/10 并发仍为用户确认的规划目标，未压测。超大消息、持续录像和慢接收压力另测。

独立业务 HTTP、已有浏览器/CDP/扩展、Firefox/WebKit、Appium/ADB 均未接入。原 R0/R1 运行 JSON 保留为 0.1.0 历史证据；历史 SaaS/Agent 资料仍保持原字节。

当前锁定版本存在两项上游弃用提示：Starlette TestClient 的 HTTPX 路径，以及 Uvicorn 的 websockets 后端。功能、原生拒绝握手与受限缓冲已通过；升级依赖时需要复核这些路径。
