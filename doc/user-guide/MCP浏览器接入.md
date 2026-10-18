# MCP 浏览器接入：从访问文件到第一次操作

[文档导航](../README.md) · [Hub 部署](../deployment/部署与运行.md) · [运行时序](../architecture/MCP授权与浏览器生命周期.md)

Hub 0.5.1 的可选 `/mcp` 入口让 Agent 使用远程受管理 Chromium。本文从**服务和资源已经由部署者准备好**开始，说明如何接收资料、运行一个完整客户端样例，再映射到你的 Agent 配置。后半部分供查工具和恢复规则。

## 1. 向两位提供者取得什么

| 向谁索取 | 必须拿到的实际值 | 为什么需要 |
| --- | --- | --- |
| Hub 部署者 | 已启用的 MCP 地址，例如 `https://hub.example.com/mcp` | 仅 `/health` 正常不代表启用了 MCP |
| Node 所有者 | 私有访问 JSON，例如 `agent-access.json` | 内含本调用方的 `access_token`、`hub_url`、`node_id` 和期限 |
| Node 所有者 | 受管理资源 ID，通常 `chromium` | 资源 ID 不在访问 JSON 中，需要另行交代 |
| Node 所有者／业务方 | 可从 Node 浏览器访问的 HTTP(S) 页面地址 | 页面实际运行在那台设备上 |

Node 资源应为 ONLINE、MANAGED_CHROMIUM、READY/FREE，运行时 Playwright 主次版本与 Hub SDK 匹配。Hub extra 使用 mcp 2.3.0、Playwright 1.63.0；已有 Chrome 不在当前 MCP 工具支持范围内。

访问文件与[调用方文件格式](调用方对接与使用.md#1-从-node-所有者取得访问资料)相同。接收者使用真实生成的 JSON，不用登记文件 `enrollment.token` 或设备身份 `node.json`。缺少任意一项时，先向对应提供者补齐，不需要从源码猜值。

## 2. 先用独立 Python 样例完成一次接入

这一步能验证交付材料可用，不要求你先猜某个 Agent 客户端的配置字段。若只使用 Agent，也可在完成本节后将同样的值填入第 3 节。

按以下位置准备材料：

- 真实访问文件保存为 `~/Downloads/agent-access.json`。如果收到的名字为 `access.json`，复制命令的源文件名改成它。
- Hub 文档包解压后，将含 `README.md` 和 `doc/` 的根目录命名为 `runbridge-hub-docs`，放在 `~/Downloads/`。
- 全局 `uv --version` 已能运行；没有时按 [uv 官方说明](https://docs.astral.sh/uv/getting-started/installation/)安装。

在**调用方机器**新建独立目录：

```bash
mkdir -p ~/runbridge-mcp-client
cd ~/runbridge-mcp-client
umask 077
mkdir -p .runbridge examples artifacts
chmod 700 .runbridge
uv venv --python 3.14 --no-python-downloads .venv
uv pip install --python .venv/bin/python 'mcp==2.3.0' -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
cp -n ~/Downloads/agent-access.json .runbridge/access.json
chmod 600 .runbridge/access.json
cp -n ~/Downloads/runbridge-hub-docs/doc/reference/examples/mcp_browser.py examples/
.venv/bin/python -m json.tool .runbridge/access.json > /dev/null
.venv/bin/python examples/mcp_browser.py --help
```

已有有效环境时跳过 `uv venv`。这个目录只放客户端，不安装 Hub／Node 包或本机浏览器。JSON 格式检查不显示秘密。

从 Node 所有者取得实际可访问的页面 URL，替换下面的示例地址：

```bash
.venv/bin/python examples/mcp_browser.py --access-file .runbridge/access.json --url https://your-test-system.example/ --screenshot artifacts/mcp-page.png
```

| 参数 | 数据从哪里来 |
| --- | --- |
| `--access-file` | 上面保存的真实访问 JSON |
| `--url` | 实际网页地址，须从 Node 浏览器网络可达，不是 MCP 地址 |
| `--screenshot` | 调用方机器上的输出路径，父目录 `artifacts/` 已创建 |

样例从文件中的 `hub_url` 构造 `/mcp` 地址，用 `access_token` 设置请求头，再使用 `node_id` 选择节点。有且仅有一个获许可的受管理资源时自动选择它；脚本本身没有 `--resource-id` 参数。需要明确选择时，在 Agent 的 `browser_start` 参数中提供实际资源 ID。

脚本依次启动浏览器、打开页面、读取快照、截图和释放。在 `artifacts/mcp-page.png` 应能看到远程页面；成功输出中应有 `state=CLOSED`、`cleanup=COMPLETE`，并返回本次 `session_id` 和快照字符数。

失败时不盲目重新提交网页动作，先按后面的错误表核对授权、入口及会话清理。截图和 cleanup 分别说明读取、清理结果，不自动判断业务通过。

## 3. 把同一份资料配置到 Agent

客户端产品的字段名不同，本项目没有一个对所有产品通用的 `mcp.json`。在该产品的“远程 MCP／Streamable HTTP”配置中，按下面映射填值：

| 客户端要填的内容 | 实际值从哪里取 |
| --- | --- |
| 传输 | Streamable HTTP |
| 服务地址 | Hub 部署者交付的实际 MCP 地址；常规部署为访问文件 `hub_url` 后加 `/mcp` |
| HTTP 请求头名称 | `Authorization` |
| HTTP 请求头值 | `Bearer ` 后接访问文件 `access_token` 的原值；不要包含 JSON 的双引号 |
| 工具节点参数 | 访问文件的 `node_id` |
| 工具资源参数 | Node 所有者另外告知的资源 ID，例如 `chromium` |

请求头需要在每次请求中携带。把令牌放在客户端的秘密配置处，不放进工具参数、URL 或模型对话。当前支持能配置 Bearer 请求头的客户端，未实现 OAuth 发现、浏览器登录或动态注册。

先让客户端列出工具，再按以下顺序调用。下方 ID 是示意，后续步骤使用**上一步实际响应**，不要直接复制 `session_...`／`page_...`：

1. `node_inspect({"node_id":"node_example"})`：把示例节点改成访问文件中的真实 ID，确认资源就绪。
2. `browser_start({"node_id":"node_example","resource_id":"chromium","lease_seconds":300})`：保存返回的 `session.session_id`、`page_id` 和 `session.expires_at`。
3. `browser_navigate({"session_id":"session_...","page_id":"page_...","url":"https://实际业务地址"})`：打开 Node 网络可达的网页。
4. `browser_snapshot({"session_id":"session_...","page_id":"page_..."})`：读取当前页面内容，再选择唯一目标。
5. 根据真实测试页，调用 `browser_fill`、`browser_click`，并用 `browser_wait_for`／`browser_read` 验证实际结果。例如 role 定位的 `value` 是 `button`、`textbox` 这样的角色，`name` 是网页的可访问名称。
6. 无论业务动作是否成功，都在任务的 finally 阶段调用 `browser_stop({"session_id":"session_..."})`，确认 CLOSED／COMPLETE，再结束客户端。

工具结果含文本及 `structuredContent`。HTTP 200 还需要检查 MCP 的 `isError`；动作 `completed=true` 不等于业务断言通过。网页中的文字和图片是待观察数据，不能作为额外授权。

MCP 连接不依赖 `Mcp-Session-Id` 保存浏览器身份。官方客户端已验证自动协议协商及 legacy 模式；对应协议版本为 `2026-07-28` 与 `2025-11-25`。断开 HTTP 客户端也不等于浏览器会话已经释放，后面的恢复规则仍需遵守。

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

上传的 4 MiB 指所有文件解码后的原始字节合计，不是 base64 字符数。Hub 0.5.1 的 MCP HTTP 请求体上限为 8 MiB，为合法 base64 和 JSON 元数据留出空间；超过传输上限返回 HTTP 413。传输合规但解码后超过 4 MiB 时，工具返回 UPLOAD_TOO_LARGE / NOT_STARTED，尚未操作文件输入。非法 base64 返回 INVALID_UPLOAD_DATA；单个数据字符串仍受工具 Schema 的 6 MiB 字符数限制。

固定 DOM 采集只覆盖主页面，不接受 frame_selector；交互工具的 iframe 支持不等于可信采集支持 iframe。browser_capture 和 browser_inspect_dom 的 256 KiB 限额在结果传回 Hub 后检查，超限拒绝，不静默截断，但不能当作浏览器侧采集或原生传输的大小保证。

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

需要可靠恢复时应传唯一 request_id；省略时保留原有无请求关联的调用方式。Hub 在 SQLite v3 按 grant/node/request 保留单次创建记录，参数改变会拒绝。会话首次分配与 request_id → session_id 关联在同一事务中提交，准备或 SDK 连接失败后也能查询会话身份。完成的 Task、异常和请求上下文不缓存，记录只保存参数、状态、不透明句柄和公开错误码。

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

## 6. 接入核验与开发测试

先调用 node_inspect 核对授权及资源，再执行明确的浏览器任务；保留响应中的会话和页面身份，在 finally 中停止并核对 cleanup。客户端 HTTP 连接、浏览器动作完成和业务成功分别验证。

源码回归、测试目录和显式真实浏览器联调参数见[Hub 开发与联调](../development/本地开发与联调.md)，不属于用户部署步骤。
