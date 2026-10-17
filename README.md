# RunBridge Hub

RunBridge Hub 是节点接入与浏览器连接的服务端，提供访问授权、会话管理、原生浏览器协议转发、画面数据流和可选 MCP 工具。

当前版本 **0.5.1**，配套 Node **0.5.0**。正常部署时，Hub 运行在独立服务器，Node 在浏览器所有者的设备主动连接本服务。

## 部署 Hub

按[部署与运行](doc/deployment/部署与运行.md)在服务器安装 Hub wheel、生成登记文件、配置远程监听及可选 MCP。文件格式、字段和命令参数见[Hub 配置与凭据](doc/reference/部署配置与凭据.md)。

部署后向 Node 所有者交付可达的 Hub 基址和登记文件；其设备操作由 RunBridge Node 项目文档负责。然后按[Hub 接入检查](doc/user-guide/快速开始.md)核验服务与远程上报。

## 接入 Hub 的公开接口

- [HTTP 与官方 SDK](doc/user-guide/调用方对接与使用.md)：使用已有访问许可申请、操作和释放远程浏览器会话。
- [MCP 浏览器工具](doc/user-guide/MCP浏览器接入.md)：Agent 通过 Bearer 授权使用受管理 Chromium。
- [画面流订阅](doc/user-guide/浏览器画面流接入.md)：调用方接收并展示会话 PNG。
- [接口总览](doc/reference/对外接口总览.md)、[完整调用方示例](doc/reference/examples/README.md)、[运行与排障](doc/deployment/运行与排障.md)。

Hub 提供数据接口，展示由调用方完成。业务动作及断言由调用方负责；资源清理完成不等于业务测试通过。

## 开发与维护

源码安装、构建、测试及同机 Hub／Node 联调见[本地开发与联调](doc/development/本地开发与联调.md)。完整架构、历史设计和验收记录见[文档导航](doc/README.md)。

机器私有调试资料保存在 Git 忽略的 `local/`；它们用于开发调试，不随部署包分发。
