# MCP 浏览器接入

适用于 Hub 0.8.1 / Node 0.7.0，在 Agent 或调用方机器操作。Hub 已启用 `/mcp`，Node 提供 READY/FREE 的 managed 资源，所有者已交付真实 `access.json` 和资源 ID。borrowed 资源通过项目 HTTP 操作。

## 连接信息

MCP 地址为访问文件 `hub_url` 后加 `/mcp`，认证头为 `Authorization: Bearer <access_token>`。在所用 Agent 的 MCP 设置里选择 Streamable HTTP，填写实际地址和私有认证头；不要把秘密放入 URL。基础 Agent 配置由该客户端官方文档管理，本项目不规定各客户端的配置文件格式。

使用官方 **MCP** Python 客户端的可运行示例见 [mcp_browser.py](../reference/examples/mcp_browser.py)。它不使用 Playwright SDK。需要示例支持的 `mcp==2.3.0` 客户端环境；可在独立 `.venv` 使用 uv 安装该依赖：

```bash
uv pip install --python .venv/bin/python 'mcp==2.3.0' -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/python mcp_browser.py --access-file access.json --url https://example.com --screenshot mcp-page.png
```

示例和访问文件先复制到自己的调用目录，基础 Python/uv 要求同[HTTP 教程](调用方对接与使用.md)。完成后输出 CLOSED/COMPLETE 并保存 PNG。

## 工具顺序与参数

先 `node_inspect(node_id)`；再 `browser_start(node_id, resource_id, request_id, lease_seconds)`，保存返回的 session_id/page_id。启动 request_id 可自行给唯一标识，同 ID 找回同一分配；`browser_sessions(node_id, request_id)` 可查询启动结果。默认 lease_seconds=300，范围 1～3600，受许可期限限制。

启动结果中的会话 ID 位于 `session.session_id`，页面 ID 位于顶层 `page_id`；后续页面工具使用这两个真实值。`browser_stop` 的关闭结果也在 `session` 中，检查 `session.state=CLOSED` 和 `session.cleanup=COMPLETE`，不要从顶层读取这些字段。

所有涉及页面的工具传 session_id/page_id。元素 target 格式为 `{"by":"role","value":"button","name":"保存"}`；by 可为 role/label/text/test_id/css，匹配采用唯一目标，role 的 name 和标签/文本采用精确匹配。iframe 加 `frame_selector`，例如 `{"by":"label","value":"用户名","frame_selector":"#login-frame"}`。定位不唯一会返回 AMBIGUOUS_TARGET。

| 工具 | 用途与关键参数 |
| --- | --- |
| node_inspect | 当前许可的节点能力 |
| browser_start / browser_sessions / browser_status / browser_stop | 申请、找回、查询、释放会话 |
| browser_navigate / browser_navigate_back | HTTP(S) 导航／返回 |
| browser_snapshot / browser_inspect_dom / browser_capture | 语义快照／固定 DOM 检查／声明式采集 |
| browser_fill / browser_click / browser_read / browser_wait_for | 填写、点击、读取、等待真实状态或值 |
| browser_press_key / browser_select_option / browser_check | 按键、按 value 选择、设置勾选 |
| browser_hover / browser_drag / browser_scroll / browser_resize | 悬停、拖拽、滚动、调整视口 |
| browser_frames / browser_tabs / browser_handle_dialog | iframe 目录、标签页和一次性弹窗策略 |
| browser_file_upload / browser_screenshot | 显式文件数据／PNG 图像 |
| tool_request_status | 新增：按 session_id/request_id 查询动作，不重放 |

原有 26 项工具保留，新增请求查询后共 27 项。精确类型、默认值和可选字段以 `tools/list` 的 inputSchema 为准；常用 timeout_ms 默认 10000，范围 1～30000。

capture 的 captures 字典每项指定 mode、selector 等，allowed_origins 必须包含读取当时的页面 origin，如 `https://example.com`，不带路径或尾部 `/`。不接受任意脚本。file_upload 每项含 name/mime_type/data（base64），最多 32 项、解码合计 4 MiB，空数组清空。screenshot 返回 MCP 图像内容，PNG 最大 2 MiB。handle_dialog 在点击前设置一次策略，默认拒绝弹窗，策略只消费一次。

示例任务顺序：start → navigate → snapshot/inspect_dom → fill → click → wait_for/read/capture → screenshot → stop。检查表单提交后的真实文本或业务记录。完成后必须检查 `browser_stop` 返回 cleanup=COMPLETE。

## 错误与找回

动作返回 request_id；`isError=true` 时查看 code 和 execution_outcome。OPERATION_TIMEOUT、OPERATION_INTERRUPTED 可能伴随 OUTCOME_UNKNOWN，不能盲目再次提交。REQUEST_IN_PROGRESS 时使用 `tool_request_status` 查询原动作。该工具也能查询 HTTP 提交的指令；截图查询仍返回图像内容。

MCP 客户端断开不会自动结束会话，它持续到显式 stop、租期到期、许可撤销或失联清理。同一许可可重新连接，通过 browser_sessions/status 找回。另一份许可不能接管已有会话。Hub/Node 重启不会恢复旧对象或自动重做动作。

HTTP 401 检查访问文件期限和撤销；421 检查 Hub MCP 允许的 Host；403 检查 Origin 与资源范围。Hub 未启用 MCP 时返回 404。以上 Hub 参数由其部署者调整。
