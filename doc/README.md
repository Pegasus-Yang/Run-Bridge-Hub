# RunBridge Hub 文档导航

[项目首页](../README.md)

本导航对应 Hub **0.5.1**。用户文档只说明本服务的部署、运维和公开接口接入；远程 Node 的安装及浏览器准备由 Node 项目维护。

## 服务部署者

1. [部署与运行](deployment/部署与运行.md)：Hub wheel 安装、文件准备、远程监听、MCP、网络、备份与升级。
2. [Hub 配置与凭据](reference/部署配置与凭据.md)：登记文件格式、Hub 全部启动参数和调用方访问文件。
3. [Hub 接入检查](user-guide/快速开始.md)：健康、远程节点上报和授权检查。
4. [运行与排障](deployment/运行与排障.md)：Hub 进程、数据库、网络、MCP 和授权故障。

## Hub 接口使用者

- [调用方对接与使用](user-guide/调用方对接与使用.md)：独立调用环境、HTTP 与官方 Playwright SDK。
- [MCP 浏览器接入](user-guide/MCP浏览器接入.md)：Agent 客户端配置、工具参数与恢复。
- [浏览器画面流接入](user-guide/浏览器画面流接入.md)：发现入口、订阅、选页与展示。
- [接口总览](reference/对外接口总览.md)、[会话与原生连接](reference/会话接口与原生连接.md)、[画面接口](reference/浏览器画面流接口.md)、[R1 接口](reference/R1接口与控制协议.md)。
- [完整示例](reference/examples/README.md)：调用方脚本、页面和接口数据。

## 开发者与维护者

- [本地开发与联调](development/本地开发与联调.md)：源码依赖、构建、回归及同机 Hub／Node 调试。
- [基础实现](architecture/R0与R1实现.md)、[会话管理](architecture/Playwright执行与会话管理.md)、[Chrome 授权与清理](architecture/Chrome复用与授权清理.md)、[画面采集与分发](architecture/浏览器画面采集与分发.md)、[MCP 生命周期](architecture/MCP授权与浏览器生命周期.md)。
- [项目概况](project/项目概况.md)、[方案总览](project/方案总览.md)、[范围调整](project/范围调整记录.md)。
- 设计阅读：[范围与架构](design/节点服务范围与架构.md)、[技术栈](design/Python3.14技术栈可行性.md)、[存储](design/管理网关与存储选型.md)、[原生契约](design/节点接入与原生执行契约.md)、[执行工具](design/客户端与执行工具接入.md)、[验证计划](design/最小实现与验证计划.md)。
- [MCP 实施前方案](design/Hub的MCP浏览器自动化实现方案.md)、[运行时序](design/Agent到Node的MCP运行时序.md)、[DSH 审查](design/DSH接入扩展审查.md)、[画面扩展方案](design/Browscreen可选扩展与浏览器画面流方案.md)、[公开依据](reference/公开依据与研究边界.md)。

## 历史验收资料

[MCP 闭环](project/MCP浏览器闭环验收记录.md)、[DSH 修复](project/DSH扩展修复验收.md)、[DSH 联调](project/DSH与受管理画面联调.md)、[画面流](project/浏览器画面流验收记录.md)、[虚拟机跨机器](project/虚拟机Node跨机器验收记录.md)、[Chrome](project/R4Chrome复用验收记录.md)、[Playwright](project/Playwright阶段验收记录.md)、[R0/R1](project/R0与R1验收记录.md)。

历史版本、地址和进程状态只代表当次验收，不作为新部署步骤；早期完整归档位于 `project/history/`。当前机器私有资料在根目录 `local/`。
