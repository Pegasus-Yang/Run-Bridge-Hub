# Chrome 复用快速开始

[文档导航](../README.md) · [首次登记](快速开始.md) · [调用方指南](调用方对接与使用.md) · [授权与清理](../architecture/Chrome复用与授权清理.md)

适用于 Hub 0.5.1 / Node 0.5.0。本模式连接所有者明确授权的已有 Chrome/Chromium 实例，复用其原页面、Cookie 和 localStorage。Node 不启动或关闭这个浏览器，也不复制 Profile。先完成 Hub 启动、Node 登记；如果先运行了仅控制模式，正常停止该 Node，再按本指南启动。

## 1. 确认授权和前置条件

- Chrome 运行在 Node 同一机器，有所有者确认的本机浏览器级 CDP WebSocket。
- 端点形如 ws://127.0.0.1:9222/devtools/browser/浏览器ID；不是 /devtools/page/，也不是另一个远程机器的地址。
- 授权范围是整个浏览器实例可见的页面、上下文和存储。通过 URL 找一个页面，不构成服务端单标签页授权。
- 此模式不需要 Node.js/npm，不执行 prepare-playwright。需要画面时在 Node 环境安装 visual extra。

Chrome 136 起，远程调试开关对默认用户数据目录有额外限制。没有现成授权入口的日常浏览器不能靠进程发现直接接管；使用独立测试 Profile 或所有者已有的合规入口。[Chrome 官方说明](https://developer.chrome.com/blog/remote-debugging-port)

## 2. 没有测试入口时，由所有者启动独立浏览器

已有授权入口时直接进入下一步。以下命令只用于自己新建测试实例，不会把已经运行的日常窗口自动变成可调试窗口。先在 Node 项目根目录运行，并保持浏览器存在。

macOS 示例：

```bash
'/Applications/Google Chrome.app/Contents/MacOS/Google Chrome' --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$PWD/.runbridge/chrome-profile" --no-first-run
```

Linux 示例，选择机器实际已有的命令（可能是 google-chrome、chromium 或现有缓存的可执行文件）：

```bash
google-chrome --remote-debugging-address=127.0.0.1 --remote-debugging-port=9222 --user-data-dir="$PWD/.runbridge/chrome-profile" --no-first-run
```

这不是浏览器安装命令。需要无界面实例时，所有者按目标环境选择 --headless=new；浏览器系统依赖须完整。浏览器页面通过 Node 网络访问业务系统，先由所有者完成登录并打开需要复用的页面。独立 Profile 与日常登录不互相复制。

## 3. 保存本机授权配置

只对上述所有者已确认的调试端口做一次本机查询，生成配置。下面在 Node 源码根目录执行；wheel 安装使用 .venv/bin/python。

```bash
uv run --locked --no-sync python - <<'PYCODE'
import json
import os
from pathlib import Path
from urllib.request import ProxyHandler, build_opener

opener = build_opener(ProxyHandler(proxies={}))
with opener.open(fullurl="http://127.0.0.1:9222/json/version", timeout=5) as response:
    browser = json.load(response)
path = Path(".runbridge/chrome.json")
path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
values = {
    "resource_id": "chrome",
    "authorization_scope": "BROWSER_INSTANCE",
    "cdp_endpoint": browser["webSocketDebuggerUrl"],
}
descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(descriptor, "w", encoding="utf-8") as output:
    json.dump(values, output, ensure_ascii=False, indent=2)
print("Chrome 授权配置已保存，未输出本机调试地址")
PYCODE
```

不是 9222 时将查询地址改为实际明确授权的端口；本指南不扫描端口。已有 chrome.json 时不覆盖，核对其中的实例端点是否仍有效。配置也可按[JSON 示例](../reference/examples/Chrome节点配置.json)手工保存，POSIX 上 chmod 600 .runbridge/chrome.json。

字段只有 resource_id（默认 chrome）、authorization_scope（必须 BROWSER_INSTANCE）、cdp_endpoint（固定本机浏览器级 ws 端点）。Node 不接受 HTTP 自动发现地址、页面端点、调用方提交的浏览器地址或启动参数。

## 4. 启动 Node 并确认 READY/FREE

```bash
uv run --locked --no-sync runbridge-node run --config .runbridge/node.json --chrome-config .runbridge/chrome.json
```

保持终端运行。Node 实际读取 Browser.getVersion，Chrome 不可达时可连接 Hub，但资源为 UNAVAILABLE。此时 ONLINE 不等于浏览器就绪。--chrome-config 与 --playwright-config 互斥。

## 5. 签发 Chrome 专用许可

在 Node 的另一个终端：

```bash
uv run --locked --no-sync runbridge-node grant --config .runbridge/node.json --resource-id chrome --expires-in 3600 --output .runbridge/chrome-access.json
uv run --locked --no-sync runbridge-node inspect node_example --access-file .runbridge/chrome-access.json
```

node_example 替换为实际 ID。预期 backend=chrome-cdp、kind=BORROWED_CHROME_CDP、readiness=READY、occupancy=FREE、authorization_scope=BROWSER_INSTANCE。实际 resource_id 若自定义，签发和调用时一起替换。

把访问文件交付给可信调用方，Node 身份和本机端点仍在所有者机器。许可一小时后到期，需要重新签发新文件；已存在的输出文件不覆盖。调用方环境按[对接指南](调用方对接与使用.md)准备 Playwright 1.63.0 和 HTTP 客户端。

## 6. 用官方 SDK 读取原页面

在 Node 源码根目录的另一个终端：

```bash
uv run --locked --no-sync python doc/reference/examples/执行会话调用.py --access-file .runbridge/chrome-access.json --resource-id chrome --page-url 'https://your-test-system.example/account' --screenshot .runbridge/chrome.png
```

替换为已打开页面的精确 URL；示例要求唯一匹配，只取标题与截图。它先 POST 申请 → 官方 connect_over_cdp(no_defaults=True) → 读取已有 page → 关闭连接 → DELETE 释放。成功输出包含 ACTIVE 和最后的 cleanup=COMPLETE，截图在调用方本机。

无 Node 包的独立调用方也可运行同一脚本，见[调用环境准备](调用方对接与使用.md)。原 Node 项目还保留 examples/chrome_reuse.py 的简洁示例，但上述文档示例完全只依赖公开接口。

多页或弹窗由官方 SDK 直接操作；保留登录应使用已有 browser.contexts/context.pages，不新建独立 context。需要操作实际业务时在示例标记位置加入 Page/Locator 动作和断言。

## 7. 可选实时画面

在 Node 环境安装扩展后，正常重启 Node；Chrome 不用重新启动：

```bash
uv sync --locked --extra visual --python 3.14 -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
uv run --locked --no-sync runbridge-node run --config .runbridge/node.json --chrome-config .runbridge/chrome.json
```

Hub 不安装 Browscreen。再用同一执行示例加 --hold-seconds 60，在 ACTIVE 期间按[画面接入](浏览器画面流接入.md)查询并订阅。只有一个页时自动选定，多页需明确选择采集目标；它不改变整个实例授权，也不自动激活业务页面。

## 8. 释放、停止与浏览器重启

```bash
uv run --locked --no-sync runbridge-node session close session_example --access-file .runbridge/chrome-access.json
uv run --locked --no-sync runbridge-node revoke grant_example --config .runbridge/node.json
```

ID 用真实返回值替换。正常释放、撤销或 Ctrl+C 停止 Node 结束借用连接与自身采集，不退出 Chrome、不清除登录。page.close()、导航、退出账号等业务操作仍会真实影响原实例，不因断开而回滚。

Chrome 重启后浏览器 ID 通常变化：所有者重新确认端点，用新本地配置文件保存，并重启 Node 完成探测。Node 不自动换绑同端口的新实例；保留稳定 node.json，旧 SDK 对象失效后申请新会话。

CDP 能力覆盖不同于 Playwright 原生协议。当前验收包含 macOS 及 Ubuntu ARM64 的特定组合；任意 Chrome 版本、锁屏、最小化和完整高级功能没有统一保证。错误与清理未知见[排障](../deployment/Playwright运行与排障.md)。
