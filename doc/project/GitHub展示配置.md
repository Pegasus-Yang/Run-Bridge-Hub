# GitHub 展示配置

本仓库对应 [Pegasus-Yang/Run-Bridge-Hub](https://github.com/Pegasus-Yang/Run-Bridge-Hub)，浏览器执行端为 [Run-Bridge-Node](https://github.com/Pegasus-Yang/Run-Bridge-Node)。

## About 信息

在仓库首页 About 的设置中使用以下文案：

| 字段 | 内容 |
| --- | --- |
| Description | 通过 HTTP / MCP 统一访问远程浏览器：Node 接入、独占租约、会话路由、页面画面与只读节点总览。 |
| Website | `https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/README.md` |
| Topics | `runbridge` `browser-automation` `remote-browser` `playwright` `mcp` `python` `self-hosted` `websocket` |

README、LICENSE 与包元数据随代码推送；Description、Website 和 Topics 是独立的 GitHub 仓库设置，需要另行保存。

## 展示内容维护

- 主页提供中英文 README，中文为默认入口，包含项目介绍、Python 与许可证徽章、节点总览截图、架构图和源码安装步骤。
- 截图来自已有的本地验收场景，保留图注；更新截图时核对页面与当前功能，避免包含口令或私有环境信息。
- 更新版本时同步主页中的两端版本关系、安装命令与 `pyproject.toml`，按[发布规范](../development/版本发布与本地打包.md)完成构建与检查。
- 许可证正文位于根目录 `LICENSE`；第三方图标保留原授权，包中的许可证清单由 `pyproject.toml` 的 `license-files` 定义。
- 贡献入口为根目录 [CONTRIBUTING.md](../../CONTRIBUTING.md)，运行与使用资料由[文档导航](../README.md)汇总。

中英文用户文档分别由 `doc/README.md` 与 `doc/README.en.md` 导航；修改功能说明、命令或参数时同步两种语言。架构、设计及历史验收资料保留中文，并在英文导航中注明。
