# Playwright method reference

[简体中文](Playwright方法表.md) · English

Tool API **1**, execution protocol **2**. These **33 methods** are explicitly implemented project methods, not a promise of the full official SDK. Except screenshots, results use `result.kind=json` and its `value` field.

Every method accepts `timeout` in milliseconds, default **10000**, range **1–30000**, including queue time. The table lists other parameters. Element targets use a Page reference plus a nonempty unique locator. Viewport limits also apply to `browser.new_context`.

Borrowed mouse, keyboard, and form input activates the specified Page before execution, avoiding background animation-frame waits. Read-only queries and streaming do not activate it. Clients must confirm references; identical URLs do not identify the same page.

| Method | Target | Other parameters and defaults | JSON value / binary result |
| --- | --- | --- | --- |
| `browser.contexts` | browser | None | Context reference array |
| `browser.new_context` | browser | viewport={width:1280,height:720}; locale=zh-CN | New Context reference |
| `context.pages` | context | None | Page reference array |
| `context.new_page` | context | None | New Page reference |
| `context.close` | context | None; original borrowed context cannot be closed | completed |
| `page.goto` | page | Required HTTP(S) url; wait_until=domcontentloaded, also commit/load/networkidle | url/title/http_status |
| `page.go_back` | page | wait_until=domcontentloaded | url |
| `page.title` | page | None | String |
| `page.url` | page | None | String |
| `page.frames` | page | None | frames: name/url list |
| `page.close` | page | Explicitly closes selected page | completed |
| `page.aria_snapshot` | page | Snapshot at most 20000 characters | url/title/snapshot/truncated |
| `page.screenshot` | page | full_page=false; PNG up to 2 MiB; no path | kind=binary: mime_type/encoding/size/data |
| `page.set_viewport_size` | page | Required viewport_size={width,height}; width 320–4096, height 200–4096 | width/height |
| `page.keyboard.press` | page | Required key, e.g. Enter or Control+A | completed/url |
| `page.mouse.wheel` | page | delta_x=0, delta_y=600 pixels | completed |
| `locator.fill` | locator | Required value, up to 20000 characters | completed |
| `locator.click` | locator | button=left; also right/middle | completed/url |
| `locator.press` | locator | Required key | completed/url |
| `locator.hover` | locator | None | completed |
| `locator.select_option` | locator | Required value: list of 1–128 option-value strings | selected: actual values |
| `locator.set_checked` | locator | Required boolean checked | checked: actual state |
| `locator.drag_to` | locator | Required target: another Page+locator description in this session | completed |
| `locator.inner_text` | locator | Up to 20000 characters | value/truncated |
| `locator.input_value` | locator | Up to 20000 characters | value/truncated |
| `locator.wait_for` | locator | state=visible; also hidden/attached/detached | completed/state |
| `locator.set_input_files` | locator | Required files array: name/mime_type/base64 data, at most 32 files and 4 MiB decoded total; [] clears | files: names |
| `runbridge.inspect_dom` | page | selector=input,textarea,select,button,a,iframe; max 200 elements and 256 KiB | url/elements(tag,attributes,text)/truncated |
| `runbridge.capture` | page | Required captures and allowed_origins; 1–128 definitions, 1–64 origins, max 256 KiB | values/url/title/truncated |
| `runbridge.wait_for` | locator | Required state=text or value, and value; waits for exact full-string equality | completed/state |
| `runbridge.tabs` | session | action=list; also new/select/close; select/close requires page_id | SessionState + page_id |
| `runbridge.dialog_policy` | page | Required accept, optional prompt_text; one-use policy, default dismiss, no waiting for dialog | configured/accept |
| `runbridge.session_state` | session | Query actual object directory | root/contexts/pages/default_page_id/ownership/last_dialog |

## Capture definitions

Each `captures` entry has `kind=dom`, `mode=text` (also number/count/visible/url/attribute/value), `selector` except for URL mode, `attribute` where needed, optional `field` for pathname from URL/href, and optional nonnegative `index`. Multiple text-like matches without an index are rejected rather than choosing the first. `allowed_origins` contains exact origins such as `https://example.com`, without path or trailing slash. Checking and reading occur in the same fixed Node script.

## References and errors

Closing a Page/Context invalidates its references. Cross-session references return OBJECT_NOT_FOUND; wrong target type returns OBJECT_TYPE_MISMATCH. Session target ID must equal the session ID. Release a browser with DELETE session; arbitrary native `browser.close` is not exposed.

Screenshots/uploads do not accept arbitrary Node-local paths. Capture does not accept scripts or callbacks. Machine-readable parameter/result schemas come from authorized `GET /v2/nodes/{id}/tools`. Inspect request status and execution outcome, then verify business records.
