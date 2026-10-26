# Playwright 方法表

简体中文 · [English](Playwright方法表.en.md)

适用于工具 playwright API 1、执行协议 2。全部 33 项均为显式实现的项目方法，不承诺官方 SDK 的其他方法。返回均包在 `result.kind=json` 的 `value` 中，截图除外。

每项均接受 timeout（毫秒），默认 10000，范围 1～30000，排队计入预算；列中只列其他参数。涉及定位的 target 使用 Page 引用加非空 locator，定位必须唯一。viewport 限制也适用于 new_context。

borrowed 的鼠标、键盘和表单输入会先激活所指定 Page，以免后台页暂停动画帧导致操作等待；只读查询和画面订阅不激活页面。Page 引用必须由调用方确认，同 URL 不表示同一页面。

| method | target | 其他参数及默认值 | JSON value / binary 结果 |
| --- | --- | --- | --- |
| `browser.contexts` | browser | 无额外参数 | Context 引用数组 |
| `browser.new_context` | browser | viewport={width:1280,height:720}；locale=zh-CN | 新 Context 引用 |
| `context.pages` | context | 无额外参数 | Page 引用数组 |
| `context.new_page` | context | 无额外参数 | 新 Page 引用 |
| `context.close` | context | 无额外参数；不得关闭 borrowed 原 context | completed |
| `page.goto` | page | url 必填 HTTP(S)；wait_until=domcontentloaded，可选 commit/load/networkidle | url/title/http_status |
| `page.go_back` | page | wait_until=domcontentloaded | url |
| `page.title` | page | 无额外参数 | 字符串 |
| `page.url` | page | 无额外参数 | 字符串 |
| `page.frames` | page | 无额外参数 | frames：name/url 列表 |
| `page.close` | page | 无额外参数；显式关闭所选页 | completed |
| `page.aria_snapshot` | page | 无额外参数，快照最多 20000 字符 | url/title/snapshot/truncated |
| `page.screenshot` | page | full_page=false；PNG 最大 2 MiB，不接受 path | kind=binary：mime_type/encoding/size/data |
| `page.set_viewport_size` | page | viewport_size={width,height} 必填；width 320～4096、height 200～4096 | width/height |
| `page.keyboard.press` | page | key 必填，如 Enter、Control+A | completed/url |
| `page.mouse.wheel` | page | delta_x=0、delta_y=600（像素） | completed |
| `locator.fill` | locator | value 必填，最多 20000 字符 | completed |
| `locator.click` | locator | button=left，可选 right/middle | completed/url |
| `locator.press` | locator | key 必填 | completed/url |
| `locator.hover` | locator | 无额外参数 | completed |
| `locator.select_option` | locator | value 必填，1～128 个 option value 字符串的列表 | selected：实际选中值列表 |
| `locator.set_checked` | locator | checked 必填布尔值 | checked：实际状态 |
| `locator.drag_to` | locator | target 必填，当前会话另一 Page+locator 描述 | completed |
| `locator.inner_text` | locator | 无额外参数，最多 20000 字符 | value/truncated |
| `locator.input_value` | locator | 无额外参数，最多 20000 字符 | value/truncated |
| `locator.wait_for` | locator | state=visible，可选 hidden/attached/detached | completed/state |
| `locator.set_input_files` | locator | files 必填数组；每项 name/mime_type/data(base64)，最多 32 项、解码合计 4 MiB；[] 清空 | files：文件名列表 |
| `runbridge.inspect_dom` | page | selector=input,textarea,select,button,a,iframe；最多 200 元素、结果 256 KiB | url/elements(tag,attributes,text)/truncated |
| `runbridge.capture` | page | captures、allowed_origins 必填；1～128 项定义、1～64 个 origin，结果 256 KiB | values/url/title/truncated |
| `runbridge.wait_for` | locator | state=text 或 value、value 必填；等待完整字符串相等 | completed/state |
| `runbridge.tabs` | session | action=list，可选 new/select/close；select/close 必须 page_id | SessionState + page_id |
| `runbridge.dialog_policy` | page | accept 必填；prompt_text 可选；预设一次策略，默认 dismiss，不等待弹窗 | configured/accept |
| `runbridge.session_state` | session | 无额外参数，查询实际对象目录 | root/contexts/pages/default_page_id/ownership/last_dialog |

## capture 定义

每个 captures 字典项含 kind=dom、mode=text（可选 number/count/visible/url/attribute/value）、selector（除 url 外必需）、attribute（取属性时使用）、field（url/href 的 pathname 可用）、index（可选的非负索引）。无 index 且文本类匹配多个元素时拒绝，不猜首项。allowed_origins 填精确 origin，如 `https://example.com`，不带路径或尾部 `/`；检查与读取发生在 Node 的同一次固定脚本中。

## 状态、引用和失败

Page/Context 关闭后旧引用失效；跨会话引用返回 OBJECT_NOT_FOUND，类型不符返回 OBJECT_TYPE_MISMATCH。session 目标 id 必须等于会话 ID。整个 Browser 的释放使用 DELETE 会话，不提供任意 browser.close 原生调用。

截图/上传不支持调用方任意 Node 本地路径，捕获不支持任意脚本或回调。完整可机器读取的参数和结果 schema 由 `GET /v2/nodes/{id}/tools` 在许可范围内返回。按请求状态及 execution_outcome 判断操作结果，再读取业务记录。
