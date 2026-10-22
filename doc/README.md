# Hub 文档导航

当前操作手册适用于 Hub **0.8.0**、Node **0.7.0**。

| 阅读目的 | 文档 |
| --- | --- |
| 快速安装、运行与验证 | [快速开始](user-guide/快速开始.md) |
| 首次部署 Hub、交付登记文件 | [部署与运行](deployment/部署与运行.md) |
| 调用已交付的节点 | [调用方对接与使用](user-guide/调用方对接与使用.md) |
| 让 Agent 使用浏览器 | [MCP 浏览器接入](user-guide/MCP浏览器接入.md) |
| 订阅操作中的实际画面 | [画面流接入](user-guide/浏览器画面流接入.md) |
| 只读查看节点、占用和实测 RTT | [节点总览](user-guide/节点总览.md) |
| 参数、文件和接口查询 | [参数详解](reference/参数详解.md)、[注释 YAML](reference/examples/Hub启动配置.yaml)、[部署配置与凭据](reference/部署配置与凭据.md)、[工具调用协议](reference/工具调用协议.md)、[完整方法表](reference/Playwright方法表.md)、[画面合同](reference/浏览器画面流接口.md) |
| 当前架构与生命周期 | [执行架构](architecture/Playwright执行与会话管理.md)、[MCP 授权](architecture/MCP授权与浏览器生命周期.md) |
| 源码模块、状态和依赖边界 | [代码结构](architecture/代码结构与执行流程.md)、[当前依赖与实现边界](reference/当前依赖与实现边界.md) |
| 故障、备份和升级 | [运行与排障](deployment/运行与排障.md) |
| 更新日志、版本与本地 tag | [版本发布记录](project/版本发布记录.md)、[本地打包与安装检查](development/版本发布与本地打包.md) |
| 开发与验证 | [本地开发与联调](development/本地开发与联调.md)、[示例](reference/examples/README.md) |
| 改造决策 | [工具指令架构方案](design/工具指令执行架构改造方案.md)、[协议设计](design/工具调用协议草案.md) |

0.5.x 及更早的 SDK 隧道、npm BrowserServer、Hub 采集方案和旧验收资料均为历史，不可用于当前部署。旧方案正文保留历史语境，Git 保存被替换手册的旧版本。私人机器配置和隔离验收原始证据位于忽略的 `local/`。

验证记录：[节点总览页面与真实状态验收](design/节点总览页面验收.md)、[YAML 启动与快速上手验收](project/YAML启动与快速上手验收.md)、[发布隔离验收](project/Python工具执行验收记录.md)、[日常环境升级与功能验收](project/日常环境升级与功能验收.md)。

`design/` 保留评审过程，旧阶段验收和 JSON 核验材料保留原日期；它们不代替当前参考合同。`project/history/` 是按原结构保存的早期研究，不作为操作手册。每份历史正文开头的状态提示优先于正文当时使用的“当前”措辞。
