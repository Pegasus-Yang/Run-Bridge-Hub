# DSH 与受管理画面联调

[文档导航](../README.md)

本轮交付 Hub/Node 0.5.0，与 DSH 测试插件 0.12.0 对接。Hub MCP 从 12 个工具扩展到 26 个，补齐原子交互、固定 DOM 采集、页面、frame、弹窗和字节上传，并在已持有的同一 Page 上持续采集 PNG；Node 探测实际 CDP 能力并修复长 TMPDIR 引起的 Chromium 启动失败。

## 已验证

- 独立 Hub 运行在 macOS，Node/浏览器在 Ubuntu ARM64 虚拟机；Python 3.14.4、Node.js 22.22.3、官方 Playwright 1.63.0。浏览器为 Google Chrome for Testing 153.0.8010.12。
- 官方 MCP Client 2.0.0 发现 26 个工具。同 request_id 重复启动得到同会话；关闭后可按原请求核对清理结果。
- 表单输入、下拉、复选框、按键、悬停、保存、固定 DOM 采集、弹窗、iframe、上传和拖拽实际执行；另从虚拟机回环 HTTP 接口核对固定名称、类型 api 和 enabled=true。
- 4 秒业务等待期间实际收到 23 个帧包、12 张不同 PNG（含状态通知带来的同编号缓存帧）；帧归属于相同 session/page/connection_generation。实际截图完成图像查看，中文、保存状态、文件名、弹窗和拖拽结果可见。
- 已确认本次会话 cleanup=COMPLETE，Node 恢复 READY/FREE。保留原有借用 Chrome 和旧 Hub，不把 SDK 断开当作清理证据。

DSH 当前 Agent 的原生执行、真实浮窗、CSV/Markdown、GitLab、恢复与报告证据汇总在插件的 `doc/project/RunBridge远程浏览器接入验收.md`；两个服务的直接协议探测不替代该层验收。

## 验证边界

持续画面适用于 Hub MCP 持有的受管理页面；普通 SDK 会话不在此范围。借用 Chrome 保留原 Browscreen 路线。本轮不认证 Windows、公网 TLS/NAT、容量压力、Firefox/WebKit、远程录像、任意执行脚本、下载或网络拦截等完整 Playwright 方法。画面只是观察，业务结果须由固定实际值判断。

- Hub 回归 76 passed、6 个本机浏览器联调跳过；Node 全量 31 passed、19 个真机相关测试跳过，真实受管理验证在 Ubuntu 上另做。
- 真实多页验证覆盖三次目标绑定、全部页面关闭后再 new；新页收到本会话的 PNG。捕获瞬时错误后恢复同一流绑定的回归通过。
