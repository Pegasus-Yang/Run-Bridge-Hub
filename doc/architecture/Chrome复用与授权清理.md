# 已有 Chrome 的授权与清理

当前 0.7.0 由 Node Python Playwright 连接所有者指定的回环 Browser CDP，使用 `connect_over_cdp(no_defaults=True)`，枚举原 context/page，而非新建上下文冒充登录复用。BROWSER_INSTANCE 明确授权整个实例；页面 URL 选择不是安全隔离。

释放 borrowed 会话只断开项目持有的连接。原 Chrome、原页面、Cookie、localStorage 继续存在，已经发生的页面操作也保留。禁止关闭原 context；整个浏览器关闭走会话释放，不暴露 Browser.close 的远程 CDP 指令。调用方显式关闭所选 page 属于授权操作。

managed 与 borrowed 的回收语义不同：前者确认本次浏览器退出和临时 Profile 清理，后者确认本次 worker/driver/画面采集连接已释放。没有直接关闭 borrowed Chrome 的“兜底”操作。清理无法确认时上报 UNKNOWN 并隔离资源，不扫描或清除其他用户进程。

运行浏览器 PID 仅用于本机归属验证：managed worker 通过公开 CDP SystemInfo 获得本次 browser PID，结合 psutil 的进程创建时间、专用 TMPDIR/Profile 检查。该信息不提供给调用方作为操作入口，不经 Hub 转发原生协议。
