# MCP browser integration

[简体中文](MCP浏览器接入.md) · English

Applies to **Hub 0.9.3 / Node 0.8.2**. On the agent/client machine, start after Hub enables `/mcp`, Node advertises a managed READY/FREE resource, and the client claims Node and saves its real access file. Borrowed resources use project HTTP. DSH users can follow the [plugin guide](DSH-Test-Plugin对接指南.en.md).

## Connection

Use access-file `hub_url` plus `/mcp`, Streamable HTTP, and `Authorization: Bearer <access_token>`. Keep the secret out of URLs. Configure the agent using its own MCP documentation; RunBridge does not prescribe client-specific config files.

The runnable [mcp_browser.py](../reference/examples/mcp_browser.py) uses the official MCP Python client, not Playwright SDK. Copy it and the access file into your client directory, prepare a Python 3.14 `.venv`, and install its supported dependency:

```bash
uv pip install --python .venv/bin/python 'mcp==2.3.0' -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/python mcp_browser.py --access-file access.json --url https://example.com --screenshot mcp-page.png
```

Expect CLOSED/COMPLETE and a PNG. See the [HTTP client guide](调用方对接与使用.en.md) for environment preparation.

## Tools and parameters

Optionally inspect with `node_inspect(node_id)`, then call `browser_start(node_id, resource_id, request_id, lease_seconds)`. Retain `session.session_id` and top-level `page_id`. Reuse the same start request ID to recover that allocation through `browser_sessions(node_id, request_id)`. Session lease defaults to 300 seconds, range 1–3600, bounded by access expiry.

Page tools use the actual session/page IDs. `browser_stop` returns its state under `session`; check `session.state=CLOSED` and `session.cleanup=COMPLETE`, not top-level fields.

Element targets use `{"by":"role","value":"button","name":"保存"}`. Supported `by`: role, label, text, test_id, css. Role names and label/text matching are exact and must identify one element. Add `frame_selector` for an iframe, e.g. `{"by":"label","value":"用户名","frame_selector":"#login-frame"}`. Nonunique matches return `AMBIGUOUS_TARGET`. Chinese strings here illustrate actual page labels.

| Tools | Purpose |
| --- | --- |
| `node_inspect` | Authorized Node capabilities |
| `browser_start` / `browser_sessions` / `browser_status` / `browser_stop` | Create, recover, query, and close sessions |
| `browser_navigate` / `browser_navigate_back` | HTTP(S) navigation/back |
| `browser_snapshot` / `browser_inspect_dom` / `browser_capture` | Semantic snapshot, fixed DOM inspection, declarative capture |
| `browser_fill` / `browser_click` / `browser_read` / `browser_wait_for` | Form operations, reads, waits for actual values/states |
| `browser_press_key` / `browser_select_option` / `browser_check` | Keypress, option values, checked state |
| `browser_hover` / `browser_drag` / `browser_scroll` / `browser_resize` | Pointer, scroll, viewport |
| `browser_frames` / `browser_tabs` / `browser_handle_dialog` | Frames, tabs, one-use dialog policy |
| `browser_file_upload` / `browser_screenshot` | Explicit file data / PNG image |
| `tool_request_status` | Query an original action by session/request ID without replay |

There are 27 tools. Exact types/defaults come from `tools/list` inputSchema. Common `timeout_ms` defaults to 10000, range 1–30000.

For capture, each `captures` entry declares mode, selector, and related fields. `allowed_origins` must include the actual page origin, e.g. `https://example.com`, without path/trailing slash. Arbitrary scripts are rejected. Uploads contain name/mime_type/base64 data, maximum 32 files and 4 MiB decoded total; `[]` clears files. Screenshots return MCP image content, at most 2 MiB PNG. Configure dialog handling before the triggering click; default is dismiss, with the policy consumed once.

Typical order: start → navigate → snapshot/inspect → fill → click → wait/read/capture → screenshot → stop. Verify actual page or business records. After stop, separately `DELETE /v1/grants/{grant_id}` with the original token and await RELEASED at batch end.

## Errors and recovery

Actions return request IDs. For `isError=true`, inspect `code` and `execution_outcome`. `OPERATION_TIMEOUT` / `OPERATION_INTERRUPTED` can accompany `OUTCOME_UNKNOWN`; query the original action instead of blindly replaying. `REQUEST_IN_PROGRESS` uses `tool_request_status`. This can also query HTTP actions; screenshot queries still return image content.

Disconnecting MCP does not close a session. It lasts until explicit stop, expiry, lease reclaim, or disconnection cleanup. The same lease can reconnect and recover sessions; another lease cannot take them over. Restarts do not restore objects or replay actions.

401: lease validity, idle reclaim, or release. 421: configured nonempty Host list. 403: Origin or ownership. 404: MCP disabled. Hub's deployer manages these settings.

## Before claiming and between cases

With only `hub_token`, use `GET /v1/pool/nodes/{node_id}/tools` to prepare/review plans before claiming; that token cannot call MCP. DSH auto-claim implements this flow. Existing-file mode uses its already held finite lease.

Inspection/status does not reset idle time. `browser_start.lease_seconds` controls a browser session, not the Node lease. Close each case's browser while retaining the batch's Node lease, then release Node on completion, cancellation, or failure before finalizing results.
