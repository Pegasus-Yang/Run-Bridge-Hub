# MCP 浏览器接入

[文档导航](../README.md) · [运行时序](../architecture/MCP授权与浏览器生命周期.md) · [受管理 Chromium 准备](Playwright快速开始.md)

当前版本为 Hub 0.5.0，提供可选 `/mcp` 入口。Agent 的 MCP 客户端通过访问许可操作 Node 上**新建的受管理 Chromium**。浏览器运行在 Node；Hub 安装 Playwright 客户端，不需要安装 Chromium。Node 0.5.0 使用控制合同版本 1 和原生 Playwright 执行协议，无需安装 MCP 包。

## 1. 准备和启动

先按[首次登记](快速开始.md)和[受管理模式](Playwright快速开始.md)完成 Node 登记、Playwright 1.63.0 运行时准备及资源探测。节点必须是 `ONLINE`，目标资源为 `MANAGED_CHROMIUM`、`READY/FREE`。浏览器是否显示窗口由 Node 所有者的 `launch_options.headless` 决定；首次运行的配置没有已有登录数据。

在 **Hub 项目根目录**安装可选依赖：

```bash
uv sync --locked --extra mcp --python 3.14 -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
uv run --locked --no-sync runbridge-hub serve --enable-mcp --enrollment-token-file .runbridge/enrollment.token
```

首次部署先按快速开始生成登记凭据；已有文件时直接使用。当前锁定 `mcp==2.3.0` 和 `playwright==1.63.0`。默认未启用 MCP，未安装 extra 的原有 Hub 仍可运行。后续运行使用 `--no-sync`；重新同步时继续指定 `--extra mcp`，防止可选依赖被移除。

| 参数 | 用法 |
| --- | --- |
| `--enable-mcp` | 开启 `/mcp`；仅安装依赖不会自动开放入口 |
| `--mcp-native-url` | Hub 内部连接自身的 HTTP(S) **根地址**，不含凭据、查询参数或路径前缀；默认按监听 host/port 推导，通配监听转换为回环地址 |
| `--mcp-allowed-host` | 额外允许的请求 Host，可重复；支持 `hub.example.com`、`hub.example.com:*`，不允许全局 `*` |
| `--mcp-allowed-origin` | 允许的网页 Origin，可重复；无 Origin 的服务端 MCP 客户端无需此参数 |

例如，外部经 HTTPS 代理访问 `hub.example.com`，Hub 本地监听 8787：

```bash
uv run --locked --no-sync runbridge-hub serve --host 0.0.0.0 --port 8787 --enable-mcp --mcp-native-url http://127.0.0.1:8787 --mcp-allowed-host hub.example.com --enrollment-token-file .runbridge/enrollment.token
```

反向代理需转发 `/mcp`，以及原有 Node 控制和原生 WebSocket 路由；带外部路径前缀时由代理剥离前缀。Host 允许列表匹配代理实际转发给 Hub 的值。非本机网络通过 HTTPS/WSS 传输访问凭据。保持 **一个 ASGI Worker**。

## 2. 签发许可并配置 Agent

在 **Node 项目根目录**，由节点所有者签发受限许可：

```bash
uv run --locked --no-sync runbridge-node grant --config .runbridge/node.json --resource-id chromium --expires-in 3600 --output .runbridge/agent-access.json
```

`chromium` 应替换为该 Node 实际的资源 ID。私有文件含 `hub_url`、`node_id`、`grant_id` 和 `access_token`。将地址和 `node_id` 交给 Agent；由 MCP 客户端的安全配置读取 `access_token`，不要把令牌写入工具参数、URL 或模型对话。

| MCP 客户端配置项 | 值 |
| --- | --- |
| 传输 | Streamable HTTP |
| 服务地址 | `http://127.0.0.1:8787/mcp`，远程环境替换为可达 HTTPS 地址 |
| HTTP 请求头 | `Authorization: Bearer <access_token>`，每次请求携带 |
| 工具上下文 | 目标 `node_id`；必要时提供 `resource_id` |

客户端的配置字段名按各自产品约定设置。本期支持可配置 Bearer 请求头的客户端；没有实现 OAuth 授权发现、浏览器登录或动态客户端注册。`node_token` 和登记凭据不能访问 `/mcp`。

官方 SDK 验证了自动协议协商和 `legacy` 模式，对应 MCP `2026-07-28` 与 `2025-11-25`。MCP 传输不承载浏览器身份；不依赖 `Mcp-Session-Id` 保存浏览器会话。

## 3. 一次完整任务

以下工具参数中的 ID 都来自上一步响应。认证头由客户端自动附加。工具结果同时提供文本和 `structuredContent`。

1. `node_inspect({"node_id":"node_example"})`：检查资源和版本。
2. `browser_start({"node_id":"node_example","resource_id":"chromium","lease_seconds":300})`：保存返回的 `session.session_id`、`page_id`、`session.expires_at`。有且仅有一个获许可的受管理资源时可以省略 `resource_id`。
3. `browser_navigate({"session_id":"session_...","page_id":"page_...","url":"https://目标页面"})`。
4. `browser_snapshot({"session_id":"session_...","page_id":"page_..."})`：观察页面后选择定位条件。
5. 在测试表单中填写：`browser_fill({"session_id":"session_...","page_id":"page_...","target":{"by":"label","value":"用户名"},"value":"测试用户"})`。
6. 点击提交：`browser_click({"session_id":"session_...","page_id":"page_...","target":{"by":"role","value":"button","name":"保存"}})`。
7. 等待并验证：`browser_wait_for({"session_id":"session_...","page_id":"page_...","target":{"by":"role","value":"status"},"state":"text","value":"已保存：测试用户"})`；必要时通过 `browser_read`、截图和业务系统查询核验。
8. 在任务的 `finally` 阶段调用 `browser_stop({"session_id":"session_..."})`。确认 `session.state=CLOSED`、`session.cleanup=COMPLETE`，然后结束 MCP 客户端。

点击返回 `completed=true` 仅表示技术动作完成。停止返回 `cleanup=COMPLETE` 表示本次浏览器资源已清理；两者都不自动证明业务测试通过。页面文本、快照和图片是来自网站的数据，Agent 不应把其中的文字视为新的授权或系统指令。

可运行的 Python 接入示例见 [mcp_browser.py](../reference/examples/mcp_browser.py)。它读取私有对接文件，完成启动、导航、快照、截图和释放；填写与提交的完整闭环由 [真实 MCP 测试](../../tests/test_mcp_live.py) 覆盖。

## 4. 当前工具合同

带页面的工具均要求 `session_id`、`page_id`。可设置 `timeout_ms`，默认 10000，范围 1–30000；计时包含同会话排队时间。浏览器创建默认租期 300 秒，范围 1–3600，最终到期时间不会超过 grant 到期时间。

| 工具 | 其他主要参数 | 结果/限制 |
| --- | --- | --- |
| `node_inspect` | `node_id` | 许可内节点和资源快照 |
| `browser_start` | `node_id`、可选 `resource_id`、`lease_seconds`、`request_id` | 新 Context、空白页，视口 1280×720、locale `zh-CN` |
| `browser_sessions` | `node_id`、可选 `request_id` | 默认列此 grant 活动 MCP 会话；指定请求时返回持久请求及已分配会话，不含其他 grant |
| `browser_status` | `session_id` | 持久会话状态及仍有效的页面 ID/URL |
| `browser_stop` | `session_id` | 幂等释放；不等待页面工具锁 |
| `browser_navigate` | `url` | HTTP(S) 地址、DOM 就绪、标题和 HTTP 状态；不接受 URL 内用户名密码 |
| `browser_snapshot` | 无 | 语义快照最多 20000 字符，包含 `truncated` |
| `browser_fill` | `target`、`value` | 输入最多 20000 字符；不强制操作隐藏元素 |
| `browser_click` | `target` | 唯一目标的普通点击，不自动重试结果未知的动作 |
| `browser_read` | `target`、`kind=text/input_value` | 最多 20000 字符，包含 `truncated` |
| `browser_wait_for` | `target`、`state`、可选 `value` | `visible/hidden/attached/detached/text/value`；后两种要求完整预期值 |
| `browser_screenshot` | 可选 `full_page` | PNG，MCP ImageContent，最大 2 MiB；不写远端文件 |

`target` 结构：`{"by":"role|label|text|test_id|css","value":"定位值","name":"可选角色名称","frame_selector":"可选 iframe CSS"}`。`role` 的 `value` 是 `button`、`textbox` 等角色，`name` 是可访问名称；其余方式不使用 `name`。文本和名称精确匹配；已有多个匹配时返回 `AMBIGUOUS_TARGET`，不默认选第一个。CSS 按 CSS 解释，不开放任意 JavaScript 执行。

页面 ID 仅在所属会话内有效。以下工具补齐正常测试所需的能力；页面工具继续要求本次 session_id/page_id，只有 browser_tabs 例外。

| 工具 | 主要参数与结果 |
| --- | --- |
| `browser_inspect_dom` | CSS selector，返回标签、属性和文本，最多 200 元素/256 KiB；用于真实定位 |
| `browser_capture` | captures 与 allowed_origins；固定 DOM 模式 text/number/count/visible/url/attribute/value，同次读取核对来源，拒绝歧义与超大结果 |
| `browser_press_key` | key，可选 target；键盘动作单独记录 |
| `browser_select_option` | target、字符串数组 values；返回实际选中的值 |
| `browser_check` | target、checked；返回实际状态 |
| `browser_hover` / `browser_drag` | 唯一 target；拖拽另有 source |
| `browser_scroll` | delta_x、delta_y；不自动缩放 |
| `browser_navigate_back` | 返回历史并等待 DOM 就绪 |
| `browser_resize` | width 320～4096、height 200～4096 |
| `browser_frames` | frame 名称和地址；操作用 target.frame_selector 明确 frame |
| `browser_tabs` | action=list/new/select/close；默认列页；select/close 要明确 page_id，可在所有页关闭后再 new |
| `browser_handle_dialog` | accept、可选 prompt_text；触发前配置下一次策略，未配置时 dismiss |
| `browser_file_upload` | target、files；name/mime_type/base64 data，合计最多 4 MiB，空列表清空 |

受管理 MCP 页面有持续 PNG 流，见[画面接口](../reference/浏览器画面流接口.md)。这些工具替代测试插件正常交互、固定采集和生命周期；不开放任意 evaluate/run_code、下载、网络拦截或整个 Playwright SDK。已有 Chrome 复用、OAuth、续租和多 Worker 不在这组 MCP 工具内。

## 5. 错误和中断恢复

认证失败在 HTTP 层返回 **401** 与 `INVALID_ACCESS_TOKEN`；工具没有执行。Host 不允许返回 421，Origin 不允许返回 403。其余执行错误通常为 HTTP 200 的 MCP `isError=true`，并在 `structuredContent` 中给出公开错误码。

| 错误/状态 | 处理 |
| --- | --- |
| `NODE_OUTSIDE_GRANT` / `RESOURCE_OUTSIDE_GRANT` / `SESSION_OUTSIDE_GRANT` | 使用正确许可；同节点的另一份许可不能接管会话 |
| `NODE_OFFLINE` / `RESOURCE_NOT_READY` / `RESOURCE_BUSY` | 查询 Node 状态，不绕过资源占用 |
| `MANAGED_RESOURCE_REQUIRED` | 指定获许可的受管理资源；不自动复用已有 Chrome |
| `PLAYWRIGHT_VERSION_MISMATCH` | Hub extra SDK 与 Node 运行时主次版本必须一致 |
| `BROWSER_CONNECT_FAILED` | 检查内部 Hub 根地址和网络；服务会请求清理已申请的浏览器 |
| `REQUEST_ARGUMENTS_MISMATCH` | 同一 request_id 的 resource_id / lease_seconds 不得改变 |
| `REQUEST_RECORD_LIMIT` / `REQUEST_CONCURRENCY_LIMIT` | 分配前拒绝；当前许可记录或 Hub 在途请求达到容量，不能删除未决记录后重放 |
| `REQUEST_OUTCOME_UNKNOWN` / `REQUEST_CANCELLED` | 按原 request_id 查询，核对 session_id 和实际 cleanup，不盲目启动第二个浏览器 |
| `SESSION_NOT_ACTIVE` / `PAGE_NOT_FOUND` | 查询当前状态，不继续使用过期句柄 |
| `AMBIGUOUS_TARGET` | 重新观察，收窄定位条件 |
| `OPERATION_TIMEOUT` / `OPERATION_INTERRUPTED` / `OPERATION_FAILED` | 写动作已进入执行阶段时标记 `OUTCOME_UNKNOWN`；先观察或查业务系统，不能盲目再次提交 |
| `cleanup=PENDING/UNKNOWN` | 清理没有确认；查询状态，不能当作 COMPLETE |

### 5.1 启动请求与失败恢复（Hub 0.5.1）

启动可传唯一 request_id，Hub 在 SQLite v3 按 grant/node/request 保留单次创建记录；参数改变会拒绝。会话首次分配与 request_id → session_id 关联在同一事务中提交，准备或 SDK 连接失败后也能查询会话身份。完成的 Task、异常和请求上下文不缓存，记录只保存参数、状态、不透明句柄和公开错误码。

`browser_sessions(node_id, request_id)` 保留 `sessions` 数组，并增加 `request`：`request_id`、`node_id`、`grant_id`、`state`、`session_id`、`error_code`、`execution_outcome`。后面三个字段在不适用时为 null。

| request.state | 含义与恢复规则 |
| --- | --- |
| PENDING | 创建在途，可能已分配 session_id；不能根据 sessions 为空推断未启动 |
| SUCCEEDED | 创建已完成；sessions 返回当前会话状态，已结束会话不会被复活 |
| FAILED | 创建失败；有 session_id 时继续核对并清理该会话；仅 session_id=null 且 execution_outcome=NOT_STARTED 证明未分配 |
| UNKNOWN | 上次进程未完成或结果未知；保留已分配身份，禁止自动重放 |
| NOT_FOUND | 同键没有记录；不表示确定未启动，也不能作为解除隔离的证据 |

非空 request.session_id 应与 sessions 中唯一项的 session_id、grant_id、node_id 一致，且该项的 request_id 匹配。request 状态不能代替真实会话的技术终态和 cleanup=COMPLETE。旧 Hub 没有 request 字段时，调用方可继续按原有唯一 sessions 项核对身份；不得把缺字段解释为未分配。

Hub 最多保留 64 个在途请求，每有效许可最多保留 1024 个不同 request_id。重复查询和相同请求不占新名额；有效许可的历史记录不按时间删除，避免重复分配。新请求受理时可回收已过期或撤销许可的请求记录，原 token 已无法通过授权，因此不能利用回收重放旧请求；会话历史元数据保留。容量拒绝发生在分配前，正常收到该错误时为 NOT_STARTED；若错误响应丢失而查询返回 NOT_FOUND，仍需保留未知状态。

MCP 调用方取消或响应丢失后，已受理的创建任务继续完成并受原租期约束。Hub 重启会将在途请求标为 UNKNOWN，保留关联供核对，不重建旧对象或重放请求。未确认清理的历史会话仍需所有者处置。

MCP HTTP 连接结束不会立即释放浏览器。客户端重连后可用同一个 grant 调用 `browser_sessions` 找回会话，再停止或继续操作；到期会自动清理。Hub 重启或 Node 断开会使原生对象失效，不能恢复旧 Page 对象。许可撤销会立刻触发会话关闭；被撤销的 token 也不能继续查询状态，应由所有者检查资源或签发新许可。

`browser_status`、`browser_stop` 沿用 REST 的 grant 归属检查，可查询/释放同 grant 通过 REST 创建的会话；页面工具只操作当前 MCP 服务持有的对象。不要对已经由 MCP 占用的原生入口再建立第二个 SDK 连接。

## 6. 验证命令

在装好 `mcp` extra 的 Hub 项目根目录运行普通回归；它默认跳过真实浏览器启动：

```bash
uv run --locked --no-sync pytest -q
```

准备好相邻 `runbridge-node` 的 `.venv` 和受管理运行时后，显式运行真实联调：

```bash
RUNBRIDGE_RUN_BROWSER_TESTS=1 uv run --locked --no-sync pytest -q tests/test_mcp_live.py
```

可用 `RUNBRIDGE_NODE_PROJECT`、`RUNBRIDGE_PLAYWRIGHT_RUNTIME` 指定目录；可用 `RUNBRIDGE_MCP_EVIDENCE_FILE` 指定脱敏 JSON 证据文件。测试只借用已安装的浏览器二进制，数据库、身份、会话目录和网页都在临时目录中。macOS 需在允许创建真实浏览器进程的环境运行；不要在受限沙箱中反复尝试启动。实际验证范围见 [MCP 验收记录](../project/MCP浏览器闭环验收记录.md)。
