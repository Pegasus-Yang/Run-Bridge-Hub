# RunBridge Hub 文档导航

- [DSH 与受管理画面联调](project/DSH与受管理画面联调.md)：0.5.0 的 MCP 替代工具、Ubuntu ARM64 实际操作、持续画面及边界。

[项目首页](../README.md)

本导航对应 **Hub 0.5.1 / Node 0.5.0 当前实现**。安装步骤、使用方法、协议参考和历史设计分开组织；首次使用按下面的顺序阅读。

## 从安装到第一次执行

| 顺序 | 文档 | 完成后应得到什么 |
| --- | --- | --- |
| 1 | [安装与运行](deployment/安装与运行.md) | Hub、Node、调用方各自的环境与依赖 |
| 2 | [首次登记与连通](user-guide/快速开始.md) | Hub 健康、Node ONLINE、私有调用许可 |
| 3A | [Chrome 复用快速开始](user-guide/Chrome复用快速开始.md) | 已有 Chrome 的 READY/FREE 资源和实例授权 |
| 3B | [Playwright 快速开始](user-guide/Playwright快速开始.md) | 受管理 Chromium 的 READY/FREE 资源 |
| 4 | [调用方对接与使用](user-guide/调用方对接与使用.md) | 官方 SDK 执行、截图与会话释放 |
| 4A | [MCP 浏览器接入](user-guide/MCP浏览器接入.md) | Agent 使用访问许可调用 26 个工具，操作并释放新建浏览器 |
| 5 | [浏览器画面流接入](user-guide/浏览器画面流接入.md) | ACTIVE 会话的 PNG 订阅与调用方展示 |
| 6 | [跨机器部署与中文字体](deployment/跨机器部署与中文字体.md) | 可达的 Hub 地址、虚拟机安装与可读的中文画面 |

3A 和 3B 是两种可选模式，同一个 Node 启动时选择其中一种。已有 Chrome 模式由 Node/Browscreen 提供画面；受管理 MCP 页面由 Hub 持有同一 Page 采集。普通 REST/SDK 受管理会话仍不提供这条独立流。

## 按职责找文档

| 读者 | 主要工作 | 推荐文档 |
| --- | --- | --- |
| Hub 部署者 | 安装、监听地址、登记凭据、SQLite、备份和升级 | [安装](deployment/安装与运行.md)、[跨机器部署](deployment/跨机器部署与中文字体.md)、[排障](deployment/Playwright运行与排障.md) |
| 继续本次本机／虚拟机测试 | 查 SSH、实际地址、操作目录、配置与数据、许可状态 | [本机与虚拟机测试环境记录](deployment/本机与虚拟机测试环境记录.md)、[完整环境快照](reference/本机与虚拟机测试环境快照.json) |
| Node 所有者 | 登记、准备浏览器、实例授权、签发和撤销许可 | [首次连通](user-guide/快速开始.md)、[Chrome](user-guide/Chrome复用快速开始.md)、[受管理模式](user-guide/Playwright快速开始.md) |
| 调用方开发者 | HTTP 会话管理、官方 SDK 执行、查询和订阅 | [对接指南](user-guide/调用方对接与使用.md)、[接口总览](reference/对外接口总览.md)、[完整示例](reference/examples/README.md) |
| 维护者 | 理解模块、协议边界、生命周期与实际验证范围 | 下方当前架构、接口参考和验收证据 |

## 当前架构与接口参考

- [MCP 授权与浏览器生命周期](architecture/MCP授权与浏览器生命周期.md)：从所有者签发许可到 Agent 操作、正常释放和异常清理的完整时序。
- [Chrome 复用与授权清理](architecture/Chrome复用与授权清理.md)、[Playwright 执行与会话管理](architecture/Playwright执行与会话管理.md)、[画面采集与分发](architecture/浏览器画面采集与分发.md)。
- [对外接口总览](reference/对外接口总览.md)：区分 RunBridge HTTP、官方浏览器协议、独立画面协议与 Node 内部入口。
- [会话接口与原生连接](reference/会话接口与原生连接.md)、[浏览器画面流接口](reference/浏览器画面流接口.md)、[R1 基础接口与控制协议](reference/R1接口与控制协议.md)。
- [运行与排障](deployment/Playwright运行与排障.md)、[R0/R1 基础架构](architecture/R0与R1实现.md)。

## 实际验收与运行证据

| 记录 | 范围 |
| --- | --- |
| [DSH 扩展修复验收](project/DSH扩展修复验收.md) | Hub 0.5.1 / Node 0.5.0 的 F1–F4 修复、107 项回归和 8 项实机验证 |
| [MCP 浏览器闭环验收](project/MCP浏览器闭环验收记录.md) | 官方 MCP 客户端、实际 Chromium、业务状态与资源清理 |
| [0.4.0 画面流验收](project/浏览器画面流验收记录.md) | 回归、可选安装、真实 PNG、权限与生命周期 |
| [虚拟机跨机器验收](project/虚拟机Node跨机器验收记录.md) | 本机 Hub 与 Ubuntu ARM64 Node、断线重连、中文字体 |
| [中文字体核验](reference/虚拟机中文字体核验记录.json) | 字体安装、实际浏览器字形和 Hub PNG |
| [0.3.0 Chrome 历史验收](project/R4Chrome复用验收记录.md) | 原有登录、实例授权与借用连接清理 |
| [0.2.0 Playwright 历史验收](project/Playwright阶段验收记录.md) | 受管理 Chromium 原生对象、输出和生命周期 |
| [0.1.0 R0/R1 历史验收](project/R0与R1验收记录.md) | 登记、心跳、查询和权限 |

原始 JSON：[画面流运行](reference/画面流运行核验记录.json)、[虚拟机运行](reference/虚拟机跨机器运行核验记录.json)、[Chrome 运行](reference/Chrome复用运行核验记录.json)、[Playwright 运行](reference/Playwright运行核验记录.json)、[R0/R1 运行](reference/R0与R1运行核验记录.json)。历史摘要和构建/静态核验记录保留原核验日期，不作为新版本当前文件摘要。

## 项目与设计资料

- [DSH 接入扩展审查](design/DSH接入扩展审查.md)：Hub/Node 0.5.0 扩展的独立审查、异常恢复问题、边界验证与修改建议。
- [Hub MCP 浏览器自动化实现方案](design/Hub的MCP浏览器自动化实现方案.md)：保留实施前取舍与后续工具规划；首个 12 工具闭环已实施，当前合同以上方接入指南为准。
- [Agent 到 Node 的 MCP 运行时序](design/Agent到Node的MCP运行时序.md)：实施前详细时序设计；已实现的关闭顺序及异常处理见当前架构。
- [项目概况](project/项目概况.md)、[完整方案总览](project/方案总览.md)、[范围调整记录](project/范围调整记录.md)。
- 设计阅读顺序：[节点服务范围与架构](design/节点服务范围与架构.md) → [Python 技术栈](design/Python3.14技术栈可行性.md) → [管理网关与存储](design/管理网关与存储选型.md) → [原生执行契约](design/节点接入与原生执行契约.md) → [执行工具接入](design/客户端与执行工具接入.md) → [实施与验证计划](design/最小实现与验证计划.md)。
- [Browscreen 实施前方案](design/Browscreen可选扩展与浏览器画面流方案.md)：保留决策过程；当前行为按架构、参考和使用指南读取。
- [公开依据与研究边界](reference/公开依据与研究边界.md)、[Python 依赖快照](reference/Python依赖核验记录.json)、[执行运行时快照](reference/执行运行时核验记录.json)、[候选运行时准备](reference/执行运行时准备记录.json)、[源码核验](reference/执行工具源码核验记录.json)。

HTTP 业务执行、设备、单标签页授权和容量仍是计划项；设计中出现这些内容不表示当前已实现。历史归档位于 `project/history/`，保持原样。
