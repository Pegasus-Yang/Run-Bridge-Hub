> 历史方案：描述 0.5.x 或更早阶段，保留当时决策语境。当前 0.6.0 已改用 Python worker；请从[当前文档导航](../README.md)操作，不照本文旧命令部署。

# Agent 通过 Hub 控制 Node 的 MCP 运行时序

> 实施状态（2026-10-13）：这是实施前的详细时序设计，原文保留。当前闭环已实现；包含本次实际关闭顺序与异常处理的图见 [MCP 授权与浏览器生命周期](../architecture/MCP授权与浏览器生命周期.md)，验证范围见 [验收记录](../project/MCP浏览器闭环验收记录.md)。

[文档导航](../README.md) · [MCP 实现方案](Hub的MCP浏览器自动化实现方案.md) · [当前执行架构](../architecture/Playwright执行与会话管理.md)

本文描述上一轮方案中的**新建受管理 Chromium** 路线：Agent 通过 MCP 调用 Hub，Hub 内的 Playwright 客户端经现有隧道操作 Node 浏览器。**MCP 层和 Hub 内的 Playwright 客户端尚未实施；节点登记、许可、控制连接、浏览器启动、原生隧道与清理来自当前 0.4.0 实现。**

先看总览，再看授权、执行和关闭细节。图中的凭据均为名称，不是实际秘密。图中的 Agent 包含负责保管凭据和发起 HTTP 请求的 MCP 客户端；模型本身不必看到 token。

## 1. 从连接到断开的完整总览

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent 与 MCP 客户端
    participant H as Hub
    participant N as 远程 Node
    participant B as Playwright 服务与 Chromium

    Note over A,H: 前置：节点所有者已向 Agent 交付 Hub 地址、node_id、access_token
    N->>H: 主动建立控制 WebSocket，携带 node_token
    H-->>N: 验证节点身份，返回连接代次
    N->>H: 上报资源与能力，后续持续心跳

    A->>H: MCP 工具发现与 node_inspect(node_id)<br/>每次 HTTP 请求携带 access_token
    H->>H: 验证许可有效期、撤销状态和节点范围
    H-->>A: 工具清单、节点和资源状态

    A->>H: browser_start(node_id)
    H->>H: 校验资源和版本，预约资源<br/>创建 PREPARING 会话
    H->>N: 控制通道发送 SessionOpen
    N->>B: 启动本次受管理 Chromium
    N->>H: 主动建立本次会话的执行隧道<br/>携带 node_token、session_id、连接代次
    N->>H: 控制通道上报 SessionPrepared
    H->>H: 会话 READY；MCP 层使用 Playwright SDK<br/>连接本 Hub 原生入口，再次校验 access_token
    H->>N: 控制通道发送 SessionConnect<br/>仅转交 SDK 请求头
    N->>B: 连接本机 Playwright 原生端点
    H->>H: 通过原生链路创建 Context 和 Page
    H-->>A: 返回 ACTIVE 会话、session_id、page_id、到期时间

    loop 观察、操作、核验
        A->>H: MCP 快照、点击、输入或截图<br/>access_token + session_id + page_id
        H->>H: 校验归属与状态，调用 Playwright SDK
        H->>N: 执行隧道转发 Playwright 原生消息
        N->>B: 本机转发并执行
        B-->>N: 结果、事件、截图或错误
        N-->>H: 原生消息返回
        H-->>A: MCP 工具结果
    end

    A->>H: browser_stop(session_id)，携带 access_token
    H->>H: 会话 CLOSING，停止新操作
    H->>N: 关闭本次执行隧道并发送 SessionStop
    N->>B: 关闭本次浏览器并回收专用临时目录
    N-->>H: 控制通道上报 SessionClosed(cleanup)
    H-->>A: 返回真实会话状态与 cleanup<br/>确认 COMPLETE 后资源可重新申请
    A->>A: 关闭 MCP 客户端或结束任务
    Note over H,N: Node 控制连接继续在线，可以承接下一次任务
```

这张图里有两个不同方向的“连接”：**Node 主动连接 Hub，让自己成为可调度节点；Agent 连接 Hub，申请和使用获授权的执行会话。** Hub 发给 Node 的命令沿 Node 已建立的连接返回，不要求 Hub 主动访问 Node 的公网端口。

总览将 Hub 内部折叠为一个参与者。后面的执行图展开 MCP 工具层和原生网关，避免误以为 MCP JSON 直接送入浏览器。

## 2. 授权从哪里来

### 2.1 三类凭据各自负责什么

| 内容 | 持有方与用途 | Agent 是否需要 |
| --- | --- | --- |
| `enrollment_token` | Hub 部署方配置，首次节点登记时使用 | 不需要 |
| `node_token` | 节点所有者及 Node 私有保存，用于节点控制连接、执行隧道和许可管理 | 不需要 |
| `access_token` | Hub 签发给指定节点的访问许可，可限制资源和到期时间 | MCP 客户端需要，通过 HTTP 头发送 |
| `node_id` | 稳定的节点标识 | 需要；它不是凭据 |
| `grant_id` | Hub 的许可记录标识 | 便于查询或撤销；它不是凭据 |
| `session_id` | 本次浏览器执行会话标识 | 启动后返回；它不是凭据 |

`access_token` 绑定一个 grant，grant 决定节点、资源范围和有效期。仅知道 `node_id` 或 `session_id` 不能获得控制权。同一节点的另一份 grant 也不能接管这次会话。

| 检查位置 | 主要拒绝条件 | 拒绝后的行为 |
| --- | --- | --- |
| Node 控制连接和会话隧道 | 节点身份错误，或隧道代次/归属不匹配 | 拒绝连接，不建立可执行路由 |
| MCP HTTP 请求 | token 无效、到期或撤销 | 拟新增入口返回 401，工具不执行 |
| 节点、资源和会话访问 | 超出 grant 范围，或会话由另一 grant 创建 | 返回相应权限错误，不向 Node 发出本次操作 |
| 创建执行会话 | 节点离线、资源未就绪/占用、SDK 版本不匹配 | 返回具体错误，不能仅凭持有 token 强行启动 |

### 2.2 首次登记、节点上线和许可交付

```mermaid
sequenceDiagram
    autonumber
    participant O as 节点所有者与本地 CLI
    participant A as Agent 的 MCP 客户端
    participant H as Hub
    participant N as Node 常驻进程

    opt 首次登记
        O->>O: 生成并私有保存 node_id 与 node_token
        O->>H: POST /v1/nodes/register<br/>Bearer enrollment_token；正文为节点身份
        H->>H: 校验登记凭据，保存 node_token 摘要
        H-->>O: 登记成功
    end

    O->>N: 启动 Node，加载身份与 Playwright 本地配置
    N->>H: WS /v1/nodes/{node_id}/control<br/>Bearer node_token
    H->>H: 校验节点身份，建立新的连接代次
    H-->>N: Welcome(generation, heartbeat 配置)
    N->>N: 启动并关闭一个探测浏览器<br/>确认运行时确实可用
    N->>H: CapabilityReport，报告 READY 与 FREE
    H-->>N: capabilities_ack
    Note over H,N: 控制连接常驻；Node 定期发送心跳，Hub 返回确认

    O->>H: POST /v1/nodes/{node_id}/grants<br/>Bearer node_token；指定资源范围与有效期
    H->>H: 验证所有者，生成访问许可并保存 token 摘要
    H-->>O: 返回 grant_id 与一次性交付的 access_token
    O->>A: 通过私有配置交付 Hub 地址、node_id、access_token
    Note over O,A: 凭据交付由所有者完成，Hub 不把 node_token 提供给 Agent

    A->>H: MCP 工具发现请求，Bearer access_token
    H->>H: 拟新增 MCP 鉴权层校验访问许可
    H-->>A: 返回工具清单，尚未启动业务浏览器
```

Node 上线时的启动/关闭是现有就绪探测；Agent 申请执行会话时会再创建新的业务浏览器。许可可以事先签发，图中顺序用于完整说明，不要求每次任务都重新登记节点或创建许可。

## 3. 启动与操作在 Hub 内如何流转

图中 M 与 H 都在 Hub 进程内。B 合并表示 Node 机器上的 Node.js Playwright 服务和它创建的 Chromium。

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent
    participant M as Hub MCP 工具层与 SDK<br/>拟新增
    participant H as Hub 会话服务与原生网关<br/>现有
    participant N as Node<br/>现有
    participant B as 本机 Playwright 与 Chromium<br/>现有

    A->>M: browser_start(node_id, resource_id 可选)<br/>Bearer access_token
    M->>H: 校验 grant 与节点，调用 SessionService.create
    H->>H: 检查在线、READY/FREE、版本与租期<br/>保存 PREPARING，预约资源
    H->>N: 控制 WS：SessionOpen(session_id, resource_id, generation)
    N->>B: launchServer，端点仅在 Node 本机使用
    N->>H: 执行 WS：/v1/nodes/{node_id}/sessions/{session_id}/tunnel<br/>Bearer node_token 与 generation
    H->>H: 核验节点身份、会话归属和当前连接代次
    H-->>N: 接受执行隧道
    N->>H: 控制 WS：SessionPrepared(session_id, runtime_version)
    H->>H: 会话转为 READY，生成 native_path
    H-->>M: READY，会话元数据与 Hub 原生路径

    M->>H: chromium.connect(native_path)<br/>Bearer access_token 与 SDK 版本请求头
    H->>H: 再次验证 grant、租期、版本、READY 状态<br/>只允许一个原生调用方，会话转为 ACTIVE
    H->>N: 控制 WS：SessionConnect<br/>只转交允许的 Playwright 请求头，不转交 Bearer
    H-->>M: 接受调用方原生 WebSocket
    N->>B: 连接本机 launchServer 端点

    M->>H: 原生 WS：new_context 与 new_page
    H->>N: 执行隧道：原样转发
    N->>B: 本机原生 WS：原样转发
    B-->>N: Context 与 Page 创建结果
    N-->>H: 原生结果
    H-->>M: 原生结果
    M->>M: 保存 SDK 对象，分配 page_id
    M-->>A: session_id、page_id、ACTIVE、expires_at

    A->>M: browser_click(session_id, page_id, target)<br/>Bearer access_token
    M->>H: 复核许可、会话归属、状态与租期
    H-->>M: 允许执行
    M->>M: 获取本会话执行锁<br/>调用 page.get_by_role(...).click()
    M->>H: 原生 WS：Playwright 操作消息
    H->>N: 执行隧道：原样转发
    N->>B: 本机原生 WS：原样转发
    B-->>N: 操作结果或错误
    N-->>H: 原生结果
    H-->>M: SDK 调用返回或抛错
    M-->>A: 结构化 MCP 结果
```

一次会话内的 Browser、Context、Page 会持续保留，后续点击、输入和截图复用这些对象，不会每次工具调用重新启动或重新连接浏览器。网页请求使用 Node 的网络；截图从浏览器经原生隧道返回 Hub，再作为 MCP 图片内容交给 Agent。

MCP HTTP 层每次请求重新校验 token；原生 WebSocket 在建立时验证一次身份，随后依靠会话状态、期限和撤销关闭进行约束。Hub 不会把 `access_token` 转发到 Node 本机 Playwright 服务或被访问的网页。

| 连接 | 建立方与用途 | 正常任务结束时 |
| --- | --- | --- |
| Agent → Hub MCP HTTP | Agent 客户端调用工具，逐请求携带 `access_token` | 停止浏览器后结束客户端即可 |
| Node → Hub 控制 WebSocket | Node 主动建立，使用 `node_token`；承载心跳和准备/停止消息 | 保留，Node 继续在线 |
| Node → Hub 会话执行 WebSocket | Node 为本次会话主动建立，使用 `node_token` 与连接代次 | 关闭 |
| Hub SDK → Hub 原生 WebSocket | 拟新增 MCP 层使用 `access_token` 建立 | 关闭 |
| Node → 本机 Playwright WebSocket | Node 连接固定本机会话端点，转发官方协议 | 关闭 |

## 4. 正常结束时如何确认已经断开

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent
    participant M as Hub MCP 工具层与 SDK<br/>拟新增
    participant H as Hub 会话服务与原生网关
    participant N as Node
    participant B as Playwright 服务与 Chromium

    A->>M: browser_stop(session_id)，Bearer access_token
    M->>H: SessionService.release(session_id, token)
    H->>H: 校验同一 grant，标记 CLOSING<br/>停止新接入并保留当前资源预约
    par 关闭调用方连接
        H-->>M: 关闭 SDK 原生连接，通知会话结束
        M->>M: 中断在途工具，使 Page 与 Frame ID 失效
    and 关闭执行隧道
        H-->>N: 关闭本次原生执行隧道
    end
    H->>N: 控制 WS：SessionStop
    Note over H,N: 隧道关闭也会触发 Node 清理<br/>不依赖 SessionStop 一定先到达
    N->>B: 关闭 helper 输入，触发 BrowserServer.close
    B-->>N: 进程退出结果
    N->>N: 核验自建进程退出，清理本次专用临时目录
    N->>H: 控制 WS：SessionClosed(cleanup)
    alt 已确认 COMPLETE
        H->>H: 会话 CLOSED，释放资源预约
        N->>H: CapabilityReport，资源 READY/FREE
        H-->>M: CLOSED，cleanup=COMPLETE
        M-->>A: 本次浏览器会话已释放
    else 未及时收到确认或清理无法确认
        H-->>M: 实际状态与 PENDING/UNKNOWN
        M-->>A: 清理尚未确认，不宣称资源已释放
    end
    A->>A: 结束 MCP 客户端
    Note over H,N: 控制连接和心跳继续，等待下一次任务
```

现有释放操作在发起关闭后等待清理报告，等待上限为 10 秒；关闭连接本身也有等待时间。超时必须读取实际返回状态，不能承诺整个停止调用一定在 10 秒内结束。重复释放是幂等操作。

`cleanup=COMPLETE` 在本图的受管理模式中表示自建浏览器进程和专用临时目录已确认回收。它不表示业务测试通过，也不表示整个 Node 服务退出。

## 5. 未按正常顺序结束时

```mermaid
sequenceDiagram
    autonumber
    participant A as Agent
    participant H as Hub MCP 与会话服务
    participant N as Node
    participant B as 本次 Chromium

    alt Agent 只断开 MCP HTTP，没有调用 browser_stop
        Note over A,H: MCP 客户端离开，或网络断开
        H->>H: 浏览器会话与 MCP 传输分开管理<br/>有效会话保留至停止或租期到期
        Note over H,N: Hub SDK 原生连接仍可存在，Node 仍可能执行已收到的动作
        H->>H: 租期到期，进入现有关闭流程
        H->>N: 关闭执行隧道并发送 SessionStop
        N->>B: 清理本次浏览器
        N-->>H: 可通信时上报清理结果
    else 所有者撤销访问许可，或许可到期
        H->>H: 使许可不可再使用，关闭相关会话
        H-->>A: 后续请求被拒绝，在途调用中断
        H->>N: 关闭执行隧道并请求停止
        N->>B: 清理本次浏览器
        N-->>H: 上报实际 cleanup
    else Node 控制连接失联
        H->>H: 会话 INTERRUPTED，cleanup 暂为 UNKNOWN
        H-->>A: 当前执行连接失效，不能自动重放操作
        N->>B: Node 若仍在运行，检测失联后回收自建浏览器
        Note over H,N: 清理成功但报告无法送达时，Hub 仍不能宣称 COMPLETE
        N->>H: 网络恢复后重新认证，建立新连接代次
        H-->>N: 新 Welcome，重新探测资源
        Note over A,N: 原会话对象不恢复；后续需要重新申请
    end
```

具体边界：

- MCP 工具尚在执行时收到取消，拟新增工具层取消等待；已发出的页面操作可能生效，需通过后续观察确认，不能承诺回滚。启动阶段取消则进入启动失败清理路径。
- Hub 内的 Playwright **原生连接**断开时，当前网关会关闭本次会话；这与 Agent 的 **MCP HTTP** 连接断开不同。
- 所有者的撤销接口返回表示撤销和关闭已发起，不表示 Node 清理报告已经收到。
- Hub 重启后，未终止的历史会话按现有逻辑标为 `INTERRUPTED/UNKNOWN`，不恢复原生对象或重放操作。已经终止的历史记录保持原状态。
- 如果 Node 进程被强杀，不能假设它执行了清理代码；以实际进程核验和当前清理状态为准。
- 真正需要让 Node 离线时，由节点所有者另行停止 Node 服务。正常停机先结束当前执行，再关闭控制连接；这不是 Agent 完成一项浏览器任务的默认步骤。

## 6. 当前直接使用 SDK 时的对应关系

当前 0.4.0 没有本文的 MCP 入口。调用方自己运行 Playwright 时，使用同一 `access_token` 调用 `POST /v1/nodes/{node_id}/sessions`，再连接返回的 Hub 原生路径，最后关闭 SDK 并调用 `DELETE /v1/sessions/{session_id}`。

拟新增 MCP 层把这段“申请会话 → 持有 SDK 对象 → 操作 → 释放”的客户端逻辑放到 Hub 内，Agent 使用工具调用完成同一流程。Node 仍然沿现有控制协议和原生隧道工作。

## 7. 当前实现的核对入口

| 时序环节 | 源码 |
| --- | --- |
| 生成并保存节点身份、登记、保存调用许可 | [Node cli.py](../../../runbridge-node/src/runbridge_node/cli.py)、[Node config.py](../../../runbridge-node/src/runbridge_node/config.py) |
| 节点身份验证、许可签发与访问验证 | [Hub service.py](../../src/runbridge_hub/service.py) 的 `register`、`create_grant`、`authorize_access` |
| Node 主动连接、能力与心跳 | [Node client.py](../../../runbridge-node/src/runbridge_node/client.py)、[Hub gateway.py](../../src/runbridge_hub/gateway.py) |
| 会话申请、原生接入、撤销与释放 | [Hub sessions.py](../../src/runbridge_hub/sessions.py) 的 `create`、`attach_caller`、`release`、`revoke` |
| Hub 原生转发与连接断开处理 | [Hub native.py](../../src/runbridge_hub/native.py) 的 `tunnel`、`execute` |
| 浏览器启动、执行隧道与清理报告 | [Node executor.py](../../../runbridge-node/src/runbridge_node/executor.py) 的 `_serve` |
| 进程与专用临时目录回收 | [Node runtime.py](../../../runbridge-node/src/runbridge_node/runtime.py)、历史 `playwright_runtime/server.mjs`（0.6.0 已移除，原内容见 Git 历史） |

本次按本地源码核对时序并补充方案说明，没有启动服务、修改运行代码或执行浏览器验收。
