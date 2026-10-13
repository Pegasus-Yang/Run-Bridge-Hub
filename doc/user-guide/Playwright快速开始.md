# 受管理 Chromium 快速开始

[文档导航](../README.md) · [首次登记](快速开始.md) · [调用方指南](调用方对接与使用.md) · [运行与排障](../deployment/Playwright运行与排障.md)

适用于 0.4.0 的受管理模式：Node 为每个执行会话启动一个独立 Chromium 服务，调用方通过官方 Playwright connect() 操作。需要复用已登录浏览器时选择[Chrome 模式](Chrome复用快速开始.md)；该模式不复用已有 Profile，当前也不提供独立画面流。

先完成 Hub 启动和 Node 身份登记。以下在 Node 源码根目录运行，wheel 部署将命令前缀改为 .venv/bin/runbridge-node。

## 1. 准备 Node.js/npm 与 Python 环境

```bash
node --version
npm --version
uv sync --locked --python 3.14 -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

Node.js/npm 是本模式的额外依赖；锁定 npm Playwright 1.63.0 的声明要求 Node.js >=20。调用方 Python SDK 使用已验收的 1.63.0，与服务主、次版本保持一致。source 的开发组已有 SDK，wheel 不自动安装它。

## 2. 准备私有运行时与浏览器缓存

```bash
uv run --locked --no-sync runbridge-node prepare-playwright --runtime-dir .runbridge/playwright
```

这个命令使用包内 package-lock.json，通过 npm ci 安装私有 Playwright，并安装 Chromium。内容位于 .runbridge/playwright：node_modules、browsers、npm-cache 与后续 sessions 临时目录；不会卸载系统浏览器或复用其他项目共享缓存。

同一锁文件目录可再次准备；若目录已有不同依赖文件，命令拒绝覆盖，选择独立新目录。源码不能只靠 Python 的 playwright install 替代这个 npm 服务运行时。

浏览器仍依赖所在系统的本机库。prepare-playwright 不自动以管理员权限安装系统库；缺少依赖时按[官方浏览器部署说明](https://playwright.dev/docs/browsers#install-system-dependencies)处理。当前受管理模式的完整验收基线是 macOS arm64，不能据借用模式的 Ubuntu 验收推断受管理 Linux 已通过。

## 3. 保存本地启动配置

将下面 JSON 保存为 .runbridge/playwright.json，或复制[配置示例](../reference/examples/Playwright节点配置.json)：

```json
{
  "runtime_directory": ".runbridge/playwright",
  "node_executable": "node",
  "resource_id": "chromium",
  "launch_options": {"headless": true}
}
```

这些路径相对 Node 启动目录，node_executable 也可使用实际 Node.js 绝对路径。launch_options 使用 Node.js launchServer 的字段名，例如 headless、proxy、executablePath；允许字段与单位见[接口配置参考](../reference/会话接口与原生连接.md)。浏览器启动设置由所有者本地决定，调用方不能通过创建会话覆盖。

## 4. 启动 Node

正常停止先前的仅控制模式 Node，再启动：

```bash
uv run --locked --no-sync runbridge-node run --config .runbridge/node.json --playwright-config .runbridge/playwright.json
```

保持终端运行。Node 会真实启动和关闭一次浏览器进行探测，再报告 READY/FREE。该探测没有调用方业务会话；后续每次会话重新启动一个本次独立实例。不带浏览器配置的 run 不开放资源，两个浏览器参数不能同时使用。

## 5. 签发受管理资源许可

在另一个终端：

```bash
uv run --locked --no-sync runbridge-node grant --config .runbridge/node.json --resource-id chromium --expires-in 3600 --output .runbridge/playwright-access.json
uv run --locked --no-sync runbridge-node inspect node_example --access-file .runbridge/playwright-access.json
```

替换 node_example。预期 backend=playwright、kind=MANAGED_CHROMIUM、READY/FREE；版本来自 npm Playwright，不是 Chromium product 版本。取得访问文件的调用方不用取得本地 playwright.json 或 Node 身份。

## 6. 执行默认无外网示例

```bash
uv run --locked --no-sync python doc/reference/examples/执行会话调用.py --access-file .runbridge/playwright-access.json --resource-id chromium --screenshot .runbridge/managed.png
```

默认使用 data URL，申请 → 官方 connect() → 新建页面 → 读取标题/PNG → SDK 关闭 → HTTP 释放。成功显示 ACTIVE，最终 cleanup=COMPLETE；PNG 在调用方机器。

访问业务系统时增加 --url http://your-internal-service/，该地址通过 Node 浏览器的网络访问。动作、Locator、Context/Page 参数及业务断言直接使用官方 SDK，完整接入与自有脚本说明见[调用方指南](调用方对接与使用.md)。

Node 源码的原 examples/playwright_smoke.py 继续保留；它依赖本机安装的 Node 包。上述文档示例不导入 RunBridge 内部代码，可以复制到独立调用方项目运行。

## 7. 输出与结束

截图、download.save_as() 和 tracing.stop(path=...) 按远程 SDK 语义保存到调用方；本地 launch_options 指定的输出目录属于 Node。完整文件传输能力按官方协议工作，实际已验收项见[历史 Playwright 验收](../project/Playwright阶段验收记录.md)。

正常释放包含 Node 自建 helper/browser 和本次临时目录清理，不删除所有者指定的外部输出目录。一个资源同一时刻只供一个会话使用；尚未确认清理时不能当作 FREE 抢占。cleanup=UNKNOWN 时按[排障指南](../deployment/Playwright运行与排障.md)核查，不通过清空身份或运行时目录解决。

当前安装 visual extra 也不会为受管理 Chromium 提供独立画面流；查询返回 UNSUPPORTED_BACKEND。需要执行期间持续 PNG 时选择已有 Chrome 路线，或由自己的 SDK 按业务需要主动 screenshot；两者是不同的调用方式。
