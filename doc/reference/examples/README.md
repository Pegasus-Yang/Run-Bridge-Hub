# Hub 调用示例

当前 0.6.0：

- [Hub启动配置.yaml](Hub启动配置.yaml)：带默认值和场景注释的服务端启动配置，使用 `serve --settings`。

- [执行会话调用.py](执行会话调用.py)：Python 标准库 HTTP，创建、选页、导航、读取、PNG 和释放；无需 Playwright。
- [mcp_browser.py](mcp_browser.py)：MCP 2.3.0 客户端，同一业务闭环；无需 Playwright。
- [画面流订阅.py](画面流订阅.py)、[HTML 查看器](画面查看示例.html)：独立观察流，按查询返回路径连接。
- [会话状态示例](会话状态示例.json)、[节点查询示例](节点查询示例.json)：示意合同，不是真实可用身份。

先取得 Node 所有者生成的真实 access.json 和资源说明，按[调用教程](../../user-guide/调用方对接与使用.md)操作。这里不包含 Node 的安装或运行步骤。
