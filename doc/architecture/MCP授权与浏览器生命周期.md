# MCP 授权与浏览器生命周期

当前 Hub 0.9.3 的 MCP 是项目方法适配层。每次 HTTP 请求从 Bearer 访问令牌解析许可，检查期限和撤销；不共享上一调用方的传输身份。Host 列表留空时不限制入口地址，非空时才校验；Origin 与请求体大小仍由 MCP 入口检查。

browser_start 选择许可内 managed 资源，复用 SessionService 的创建去重，并执行只读 session_state 激活会话；返回 session_id/page_id/request_id。其他工具只把参数转为统一 CommandService 调用，Locator、固定 DOM 读取、文件解码和截图都由 Node 执行。

browser_sessions 按许可和启动 request_id 找回会话；tool_request_status 按动作 ID 查结果。MCP HTTP 连接结束不等于浏览器释放；browser_stop、租期到期或许可撤销才触发关闭。已有的 26 项工具保留，新增请求查询，共 27 项。

详见[MCP 手册](../user-guide/MCP浏览器接入.md)与[执行架构](Playwright执行与会话管理.md)。
