# RunBridge R4 Chrome 复用验收记录

[文档导航](../README.md) · [复用架构](../architecture/Chrome复用与授权清理.md) · [调用指南](../user-guide/调用方对接与使用.md)

实施日期：2026-10-12（Asia/Shanghai），版本 0.3.0。本轮范围为 R4 的一种 Chrome CDP 实例授权路径；受管理 Chromium、R0/R1 与会话管理继续回归。原 0.1.0、0.2.0 运行及打包记录按原字节保留，不代表新版本当前源码摘要。

## 已实现

- 本机所有者明确授权固定浏览器 ID，Node 只读探测版本；调用方不能配置或替换端点。
- 资源与创建许可范围、独占、版本握手、协议入口、租期和许可撤销/到期检查。
- 复用 Chrome 已有原页面和业务登录，官方 Playwright Locator、截图、Cookie/localStorage。
- 释放及控制断开只关闭 WebSocket；Node 无用户 Chrome 进程或 Profile 清理路径。
- 拒绝 CDP 退出/崩溃浏览器命令及不透明旧式封装，旧 SDK 对象断开失效。

## 验证

全量回归通过：Hub 22 项、Node 32 项，共 54 项，零失败、零跳过。Node 包含 16 项新增 Chrome 测试，其中明确覆盖跨真实浏览器目标访问拒绝、完整示例和文档代码实际调用。运行、版本与源码摘要见[R4 运行核验记录](../reference/Chrome复用运行核验记录.json)。构建和安装核验另见[R4 构建记录](../reference/R4构建产物核验记录.json)；文档导航与历史字节核对见[R4 文档记录](../reference/R4文档核验记录.json)。

验收使用 macOS arm64、Python 3.14.7、Playwright 1.63.0、Google Chrome 154.0.8037.99。测试所有者先启动独立 Chrome Profile，通过实际 HTTP 服务登录，再启动 Node；与 Node 启动新浏览器或导入 storage_state 的场景不同。每次断开后独立直连检查业务身份、Cookie、localStorage、原目标 ID、调试附加状态和浏览器进程存活；只有测试所有者最后关闭自己创建的 Chrome。

服务端 UNKNOWN 与本机直接观察分开记录：强杀 Node/Hub 重启不能凭后续浏览器存活改写旧会话历史清理确认。

## 边界

授权为端点可见的整个浏览器实例，不提供标签页、域名或账号隔离。已打开 Chrome 必须已有所有者确认的 CDP 入口；未实现扩展或对未开启入口的默认日常 Profile 自动接管。未验证 GUI 最小化/锁屏、Linux/Windows、生产代理/TLS、任意 Chrome 版本、完整高级 CDP 功能或 100 用户/10 并发容量。HTTP 业务执行、Appium/ADB 仍为后续阶段。
