# RunBridge Hub

RunBridge Hub 为远程浏览器操作提供鉴权、资源授权、会话租期、指令路由及结果查询。浏览器由远程 Node 的 Python Playwright 启动或连接并执行操作；Hub 无需安装 Playwright、Node.js 或浏览器。

当前版本 **0.6.0**，配套 Node **0.6.0**。调用方使用本项目的 HTTP 方法合同或 MCP；不再提供官方 Playwright SDK 的远程连接入口。

- 部署 Hub：从[部署与运行](doc/deployment/部署与运行.md)开始，生成并交付登记文件。
- 使用已交付的节点：[调用方教程](doc/user-guide/调用方对接与使用.md)，包括完整可执行示例。
- Agent 接入：[MCP 浏览器接入](doc/user-guide/MCP浏览器接入.md)。
- 运行维护：[排障与升级](doc/deployment/运行与排障.md)。
- 开发者：[本地开发与联调](doc/development/本地开发与联调.md)。

完整阅读路线、架构、协议与历史资料见[文档导航](doc/README.md)。Node 的安装和设备配置由 Node 项目手册维护。
