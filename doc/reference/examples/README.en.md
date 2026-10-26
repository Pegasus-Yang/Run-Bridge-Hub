# Hub client examples

[简体中文](README.md) · English

Applies to **Hub 0.9.3 / Node 0.8.2**:

- [Annotated Hub YAML](Hub启动配置.en.yaml): defaults and scenarios for `serve --settings`.
- [node_lease.py](node_lease.py): standard-library claim/status/release helper; reads private Hub authentication JSON and writes five-field access JSON.
- [执行会话调用.py](执行会话调用.py): standard-library HTTP session, page selection, navigation, reads, PNG, and close, without Playwright.
- [mcp_browser.py](mcp_browser.py): the same workflow using MCP 2.3.0, without Playwright.
- [画面流订阅.py](画面流订阅.py) and [HTML viewer](画面查看示例.html): separate observation stream using the query's returned path.
- [Session JSON](会话状态示例.json) and [Node JSON](节点查询示例.json): protocol illustrations, not usable identities.

Follow the [client guide](../../user-guide/调用方对接与使用.en.md) to claim Node and save real `access.json`; get resource IDs from capabilities. Browser examples release their own session; use `node_lease.py release` separately at batch end. Node deployment is documented by its own repository. Shared scripts and viewer labels may emit Chinese messages; filenames and command options are identical in both language guides.
