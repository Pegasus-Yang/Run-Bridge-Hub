# Hub 文档导航

简体中文 · [English](README.en.md)

当前用户手册适用于 **Hub 0.9.3 / Node 0.8.2**。源码体验从[项目首页](../README.md#快速开始)开始，已有 wheel 的独立目录部署从[快速开始](user-guide/快速开始.md)开始。

## 按角色开始

| 角色 | 推荐阅读路线 |
| --- | --- |
| Hub 部署者 | 快速开始 → 部署与运行 → 参数与凭据 → 节点总览 → 运行与排障 |
| 程序或 Agent 调用方 | 调用方教程 → Node 租约 → HTTP 方法或 MCP → 画面与清理 |
| DSH 使用者 | DSH 插件对接 → MCP 接入 → 租约与任务收尾 |

## 使用、部署与接口

| 阅读目的 | 文档 |
| --- | --- |
| 快速安装、启动和验证 | [快速开始](user-guide/快速开始.md) |
| 独立部署、交付和备份 | [部署与运行](deployment/部署与运行.md) |
| 查询启动参数和默认值 | [参数详解](reference/参数详解.md)、[带注释 YAML](reference/examples/Hub启动配置.yaml) |
| 区分配置、身份和凭据 | [配置与凭据](reference/部署配置与凭据.md) |
| 编写调用程序、完成一次操作 | [调用方对接与使用](user-guide/调用方对接与使用.md)、[示例导航](reference/examples/README.md) |
| 领取、续租和交还整个 Node | [Node 使用权租约接口](reference/Node使用权租约接口.md) |
| 理解请求、对象和结果 | [工具调用协议](reference/工具调用协议.md)、[Playwright 方法表](reference/Playwright方法表.md) |
| 接入 Agent | [MCP 浏览器接入](user-guide/MCP浏览器接入.md) |
| 使用 DSH 自动化测试 | [DSH-Test-Plugin 对接指南](user-guide/DSH-Test-Plugin对接指南.md) |
| 订阅同一页面的画面 | [画面接入](user-guide/浏览器画面流接入.md)、[画面协议](reference/浏览器画面流接口.md) |
| 查看节点、占用和实测 RTT | [节点总览](user-guide/节点总览.md) |
| 处理错误、升级和清理未知 | [运行与排障](deployment/运行与排障.md) |
| 了解实际依赖与支持边界 | [当前依赖与实现边界](reference/当前依赖与实现边界.md) |

上述用户文档均提供对应英文版，可从每页顶部切换；[英文导航](README.en.md)直接连接英文手册。CLI、节点总览及部分示例提示仍以中文为主。

## 开发、协作与历史资料

| 阅读目的 | 文档 |
| --- | --- |
| 自动验证与 GitHub Release | [GitHub Actions](development/GitHubActions与Release.md) |
| 准备 PyPI 分发 | [PyPI 发布准备](development/PyPI发布准备.md) |
| 参与贡献与授权 | [贡献指南](../CONTRIBUTING.md)、[MIT License](../LICENSE) |
| 本地开发、验证与打包 | [本地开发与联调](development/本地开发与联调.md)、[版本发布与本地打包](development/版本发布与本地打包.md) |
| 当前架构与源码 | [代码结构](architecture/代码结构与执行流程.md)、[执行与会话](architecture/Playwright执行与会话管理.md)、[MCP 生命周期](architecture/MCP授权与浏览器生命周期.md) |
| 版本变化与 GitHub 展示 | [版本发布记录](project/版本发布记录.md)、[GitHub 展示配置](project/GitHub展示配置.md) |
| 设计过程 | [工具架构方案](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/%E5%B7%A5%E5%85%B7%E6%8C%87%E4%BB%A4%E6%89%A7%E8%A1%8C%E6%9E%B6%E6%9E%84%E6%94%B9%E9%80%A0%E6%96%B9%E6%A1%88.md)、[工具协议草案](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/%E5%B7%A5%E5%85%B7%E8%B0%83%E7%94%A8%E5%8D%8F%E8%AE%AE%E8%8D%89%E6%A1%88.md)、[Node 租约设计](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/Hub%E7%BB%9F%E4%B8%80%E8%AE%A4%E8%AF%81%E4%B8%8ENode%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%94%B9%E9%80%A0%E6%96%B9%E6%A1%88.md) |
| 已有验证记录 | [租约验收](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/Node%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%94%B9%E9%80%A0%E9%AA%8C%E6%94%B6.md)、[总览验收](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/%E8%8A%82%E7%82%B9%E6%80%BB%E8%A7%88%E9%A1%B5%E9%9D%A2%E9%AA%8C%E6%94%B6.md)、[YAML 验收](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/YAML%E5%90%AF%E5%8A%A8%E4%B8%8E%E5%BF%AB%E9%80%9F%E4%B8%8A%E6%89%8B%E9%AA%8C%E6%94%B6.md)、[发布隔离验收](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/Python%E5%B7%A5%E5%85%B7%E6%89%A7%E8%A1%8C%E9%AA%8C%E6%94%B6%E8%AE%B0%E5%BD%95.md)、[日常环境验收](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/%E6%97%A5%E5%B8%B8%E7%8E%AF%E5%A2%83%E5%8D%87%E7%BA%A7%E4%B8%8E%E5%8A%9F%E8%83%BD%E9%AA%8C%E6%94%B6.md) |

架构、设计、发布和历史验收资料保留中文。`design/` 记录决策过程，`project/history/` 保存早期研究；旧 SDK 隧道、npm BrowserServer、Hub 采集和旧验收不作为当前操作手册。历史正文的日期和状态提示优先于当时的“当前”措辞；原始记录不代表本次重新进行了运行验收。私人配置与原始证据保存在忽略的 `local/`。

源码包保留当前用户文档；未随包分发的历史方案、验收和原始核验材料通过 GitHub 链接查阅。
