# Hub YAML 启动与快速上手验收

日期：2026-10-19。版本：0.6.0。本记录说明本次配置功能和文档示例的验证范围，不替代实际部署后的检查。

## 本次实现

新增 `serve --settings hub.yaml`，支持原启动参数对应的 YAML 字段。路径相对配置文件目录，令牌文件优先于环境变量；配置错误在创建应用前退出。原 CLI 方式保留，文件方式不与其他启动参数混用。MCP 额外 Host 继续追加到内置本机列表。

两端首页参考 [uv](https://github.com/astral-sh/uv)、[FastAPI](https://github.com/fastapi/fastapi)、[Playwright Python](https://github.com/microsoft/playwright-python) 的入口组织方式，提供介绍、功能、最小启动、成功检查及使用/开发导航。基础工具准备继续引用官网，用户文档不包含另一端的部署命令。

配置合同见[参数详解](../reference/参数详解.md)，可复制[注释 YAML](../reference/examples/Hub启动配置.yaml)，实际操作见[快速开始](../user-guide/快速开始.md)。

## 自动化与隔离验证

| 验证项 | 结果 |
| --- | --- |
| Hub pytest 全集 | 104 passed、10 skipped；包含新增 15 项启动测试，默认跳过的真实浏览器测试未算作通过 |
| 配置测试 | YAML 路径、默认数据库、令牌优先级、未知/无效字段、心跳关系、MCP 通配符、CLI 兼容、混用拒绝与秘密隐藏通过 |
| 新 wheel 安装 | 独立 macOS 临时目录创建全新 Hub、Node、标准库调用方 `.venv`，不使用源码导入路径；Hub/调用方未安装 Playwright |
| 纯 HTTP 安装 | 另建全新环境只安装基础 wheel，不含 MCP/Playwright；YAML 启动成功、health 正常、MCP 默认返回 404 |
| YAML 实际启动 | 从另一工作目录仅传 `--settings` 启动，数据库创建在 YAML 目录下，health 返回协议 2 |
| 远端执行闭环 | 隔离 Node 自动登记并达到 ONLINE、READY/FREE；真实创建、查询、释放会话成功 |
| 快速开始 HTTP 示例 | Node 浏览器访问该测试 Hub 的 `/health`，返回实际 URL、保存有效 PNG，关闭为 CLOSED/COMPLETE；图片已人工检查 |
| 本机 MCP 默认 Host | YAML 启用 MCP，不追加允许 Host；通过本机 URL 发现 27 项工具，查询节点、启动与关闭浏览器成功 |
| Node 重启与许可 | 不带登记材料复用原身份重启；新增许可和撤销成功 |
| 文档与参数 | 两端 Markdown 本地文件/锚点检查通过；Hub 11 个 CLI 选项、10 个 YAML 顶层字段均在参数文档中；本次 Hub 10 个 YAML 示例通过模型校验 |

快速验证使用项目自身 HTTP 健康页，避免依赖外部网站。JSON 页面没有 HTML 标题，示例返回空 `title` 属于正常结果。导航只支持 HTTP/HTTPS，文档不使用 `data:` 或本机文件页面。

## 清理与边界

本次只运行隔离进程，未启动日常 Hub 或虚拟机 Node。结束后测试子进程均退出；日常配置与原停止记录的内容哈希未变化，原 Hub 端口仍未监听。未把本次结果描述为日常环境升级或跨机器验收。

私有配置、访问令牌、日志、数据库、截图和原始验证 JSON 保存在忽略的本机 `local/`，不进入 Git。代码静态检查、构建与依赖一致性检查一并执行。更多环境覆盖和旧版本改造结果见已有[日常环境验收](日常环境升级与功能验收.md)及[发布验收](Python工具执行验收记录.md)，两者日期和范围保持原样。
