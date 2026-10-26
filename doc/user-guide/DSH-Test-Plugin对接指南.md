# DSH-Test-Plugin 对接指南

简体中文 · [English](DSH-Test-Plugin对接指南.en.md)

适用于 Hub 0.9.3、Node 0.8.2 和 DSH-Test-Plugin 0.15.0。插件通过 Hub 的 MCP 在 Node 上执行浏览器测试，无需在 DSH 宿主安装远程浏览器或 Python Playwright。

推荐流程：**Hub 配置独立申请凭据 → Node 登记并上报能力 → 插件读取 Hub 认证文件、准备和审核计划 → 自动领取 Node → 整批执行 → 关闭浏览器并交还 Node → 封存报告**。Hub 不维护用户身份；持有申请凭据即可申请未占用的 Node，领取后的操作必须使用本次租约令牌。

## 1. 三端分别准备什么

| 角色 | 准备工作 | 交付内容 |
| --- | --- | --- |
| Hub 部署者 | 安装0.9.3，启用MCP，配置public_url与独立hub_token_file | 给Node维护者登记附件；给调用方Hub基址和独立申请凭据，两者分开 |
| Node 维护者 | 安装0.8.2，配置tools.playwright的managed资源并保持在线，实际探测通过 | node_id、resource_id、模式及设备版本；不签发访问文件 |
| DSH 使用者 | 在实际DSH宿主保存私有认证文件，安装0.15.0插件，在对应profile设置浏览器连接 | 配置、用例、预期、运行报告和清理结果 |

Hub启动配置示例（在Hub机器）：

```bash
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

已有文件继续使用，不覆盖。`hub.yaml` 在原登记配置上增加：

```yaml
hub_token_file: .runbridge/hub.token
public_url: http://hub.example:8787  # 改为实际可达基址，可含反向代理前缀。
mcp_enabled: true
grant_max_lease_seconds: 86400
grant_idle_timeout_seconds: 600
```

修改后正常重启生效。`mcp_allowed_hosts` 省略或 `[]` 时允许所有 Host；需要限制时才填入实际 MCP URL 的 Host 列表。hub.token是generate-token生成的32～256字符单行文本，与enrollment.token和Dashboard口令不同。Hub申请凭据不能直接调用MCP，Node进程也不需要它。完整部署、默认值及路径规则见[快速开始](快速开始.md)、[参数详解](../reference/参数详解.md)。

Node按其项目手册登记上线，通过Hub总览或资源池确认ONLINE、非stale、MANAGED_CHROMIUM资源READY/FREE。MCP browser_start当前只选择managed；borrowed Chrome通过项目HTTP使用。

## 2. 选择连接来源，并取得参数

插件明确区分两种来源，文件不能混用：

| 来源 | 适用情况 | 插件读取的私有文件 |
| --- | --- | --- |
| Hub自动领取（推荐） | 希望每批测试按需申请、执行并归还设备 | 仅hub_url、hub_token |
| 现成访问文件 | 已经通过Hub明确领取一份Node租约，需要交给本批测试使用 | hub_url、node_id、grant_id、access_token、expires_at |

### Hub认证文件

在**DSH实际运行机器**保存`hub-auth.yaml`，也支持同字段JSON：

```yaml
hub_url: "http://hub.example:8787"
hub_token: "请替换为Hub维护者交付的真实独立申请凭据"
```

| 参数 | 怎样取得 | 注意事项 |
| --- | --- | --- |
| hub_url | Hub部署者交付，与public_url及真实代理入口一致 | 基址后由插件追加/mcp；不填/health、/v1、/v2，不含用户名、密码、query或fragment |
| hub_token | Hub单独生成的hub.token原文 | 不加Bearer或token=；不是登记、Node身份、Dashboard或某份租约令牌 |
| 目标nodeId | Node启动日志、设备node.json的node_id，或GET /v1/pool/nodes目录 | 是稳定Node ID，不是名称、IP或资源ID；无需取得整个node.json |
| resourceId | 该Node实际能力目录，通常为chromium | 选择managed资源，不能凭空编造 |

Hub令牌只读取资源池和申请；目录不返回别人的access_token。持有者身份由令牌本身证明，不建立用户账号。

### 现成访问文件

用Hub认证调用POST /v1/nodes/{node_id}/grants，指定唯一request_id与可选lease_seconds；把**响应中的access_config**保存为私有JSON或YAML。可复制[标准库领取示例](../reference/examples/node_lease.py)，按[调用教程](调用方对接与使用.md)生成。不要把整份领取响应作为访问文件，也不要运行已移除的Node grant/revoke。

```yaml
hub_url: "http://hub.example:8787"
node_id: "node_example"
grant_id: "grant_example"
access_token: "请替换为Hub本次领取配套签发的真实令牌"
expires_at: "2030-01-01T01:00:00Z"  # 必须保留真实签发值；示例不能直接使用。
```

| 参数 | 怎样取得 | 能否自己修改 |
| --- | --- | --- |
| hub_url | Hub public_url导出 | 使用实际签发基址，保留代理前缀 |
| node_id | 此次申请路径指定的已登记Node | 与本次grant、token配套 |
| grant_id | Hub领取时新建并返回 | 不使用另一份许可ID，不用设备身份ID代替 |
| access_token | 与grant_id同时随机签发，首次响应交付 | 不可从数据库哈希、总览或共享Hub凭据取回原文 |
| expires_at | Hub按领取时长计算的带时区到期时间 | 手改本地时间不能续租；以Hub实际状态为准 |

前四项是插件解析必需字段；当前Hub导出固定包含第五项expires_at且不签发永久许可。保留整份access_config最稳妥。首次领取响应丢失后，同request_id重试只返回有限状态和token_available=false，不再次交付秘密；等待空闲回收，再以新请求领取，不能覆盖占用。

现成文件模式使用的也是整Node独占租约，插件整批结束会释放它；不要同时给其他正在工作的任务使用同一token。需要新批次时重新领取，不能继续使用已释放文件。

## 3. 在DSH中配置、读取、检测和保存

在实际运行测试的DSH profile中打开**设置 → 测试插件 → 浏览器设置**，浏览器位置选择远程RunBridge MCP，明确选择连接来源。

| 插件配置字段 | Hub模式 | 现成文件模式 |
| --- | --- | --- |
| backend | runbridge | runbridge |
| connectionSource | hub | access-file |
| hubFile | DSH宿主上的hub-auth.yaml/JSON路径 | 不使用 |
| nodeId | 目录中实际目标Node ID | 从访问文件读取 |
| accessFile | 由本批运行管理专用凭据 | 已领取的access.yaml/JSON路径 |
| resourceId | 实际managed资源，通常chromium | 同左 |
| nodeLeaseSeconds | 可留空使用Hub默认3600秒，或填写正整数 | 使用已有租约，初始期限来自文件及Hub状态 |
| leaseSeconds | 浏览器会话租期，插件默认1800秒，范围1～3600 | 同左 |
| previewEnabled | 按需显示实际画面 | 同左 |

设置页保存到browserConnection；静态profile的browser配置支持相同字段。请按当前插件的设置页或[插件远程指南](https://github.com/Pegasus-Yang/DSH-Test-Plugin/blob/main/doc/user-guide/RunBridge远程浏览器与持续预览.md)管理，不将秘密写入profile。

1. 填入私有文件路径。路径由DSH宿主读取，网页浏览器所在电脑的路径不一定可用；优先绝对路径，不写~或$HOME。相对路径按当前工作区解析。
2. 点击读取配置，检查无秘密摘要。Hub模式不需要预先填写grant_id/access_token，它们在实际领取后由Hub生成。
3. 填写目标Node和资源，检测连接。Hub模式验证资源池及只读工具目录，**不领取Node、不启动浏览器**；现成文件模式验证原租约、MCP工具与对应资源，也不启动浏览器。
4. 按需设置Node租期、浏览器会话租期及实时画面，保存浏览器设置。设置在下一批测试生效。

文件设为600、所在私有目录700，不提交Git、不放用例、不发给模型。插件只保存路径和偏好，原凭据在宿主私有文件读取；自动领取产生的执行文件由本批运行私密保存。修改来源、文件或设备后应重新读取和检测。被命令行overlay固定的设置，由DSH管理者在实际profile调整。

“文件已解析”只证明格式，“最近检测通过”只证明当时可达和可用；它们不等于业务测试通过。Node可能随后被其他申请领取，实际执行仍以Hub原子领取结果为准。

## 4. 运行首条浏览器测试

在DSH对话中输入，先把地址改为**Node浏览器实际可达的Hub健康页**：

```text
/test-plan 通过浏览器访问 http://hub.example:8787/health，断言页面正文同时包含 status、ok 和 protocol_version，保存页面截图，完成后关闭浏览器并交还本批 Node 使用权。
```

批准计划后执行。也可用/test直接执行；文件用例用/test-run cases.md，CSV参数化用/test-data data.csv --file cases.md，路径按当前对话工作区读取。命令详情见[插件使用说明](https://github.com/Pegasus-Yang/DSH-Test-Plugin/blob/main/doc/user-guide/使用说明.md)。

Hub模式先从只读目录准备和审核计划，批准后才领取；纯API用例不申请Node。整批CSV共用一份Node租约，每条用例结束关闭自己的浏览器，最后统一交还Node。MCP工具、会话与页面ID来自实际Hub结果，模型不填写秘密、本地CDP或自造session_id。

检查业务正文、断言和截图，并确认会话cleanup=COMPLETE、Node租约RELEASED。插件在正常结束、取消和失败路径均等待收尾与释放结果，再封存报告；释放未知会记录错误/隔离，不能把“已发出DELETE”当作成功。

健康页用例必须实际走浏览器。业务测试还应核对页面或最终业务记录，HTTP200、点击成功、截图或模型总结不能替代业务断言。浏览器请求从Node发出，localhost指Node；纯API请求从DSH宿主发出，两端网络分别确认。

## 5. 租期、空闲与释放

默认Node租期3600秒；用户可在申请时填写正整数，不能超过Hub当前grant_max_lease_seconds（默认86400秒，可配置）。grant_idle_timeout_seconds默认600秒、可配置。它们与浏览器会话1～3600秒的限制分开。

实际会话创建、页面操作、DOM/截图读取计入使用；有效且有界的在途执行期间暂停空闲，完成后重新计时。MCP握手、工具列表、node_inspect、browser_status、状态轮询、画面、Node心跳和续租均不刷新空闲。浏览器一直开着也可能被回收。

插件使用原令牌续租；续租不延长已有浏览器会话、不复活已失效租约。任务结束先关闭会话，再释放Node并等待RELEASED；QUARANTINED表示待核查，继续阻止其他领取。原令牌失效后仍可查询原grant终态或重复释放，不能接管新租约。

实时画面按本会话visual路径订阅同一Page，不手填浏览器端口；画面过期或结束应撤除旧图。远程模式提供PNG预览和报告截图，不提供远程录像。底层见[画面指南](浏览器画面流接入.md)。

## 6. 排障

| 现象 | 处理方式 |
| --- | --- |
| 文件读取失败 | 核对DSH宿主实际路径、权限和明确选择的来源；Hub文件与访问文件字段不能混用 |
| HUB_ACCESS_NOT_CONFIGURED / PUBLIC_URL_REQUIRED | Hub部署者补齐独立申请凭据与public_url并重启 |
| 领取401 | 核对hub_token角色；Node身份、登记、Dashboard或旧access_token不能代替 |
| NODE_LEASE_BUSY | 等原租约交还；不换request_id抢占，Hub不提供预约或强制接管 |
| Node离线/资源未就绪 | 设备维护者检查原进程、网络、心跳、Playwright和Chromium实际探测，不重建身份解决网络问题 |
| 执行/续租401 | 查看原租约的到期、空闲或释放原因；不换令牌继续本次已发生的动作 |
| 领取响应未知/没有首次令牌 | 保留本批申请记录，等待原占用回收；不得自动生成第二份申请继续跑 |
| LEASE_TOO_LONG | 降低本次Node租期或由Hub部署者调整上限；插件不硬编码一天 |
| MCP421/403 | 421核对已配置的非空Host列表；省略或[]不限制Host。403核对Origin及资源/会话归属 |
| OUTCOME_UNKNOWN | 查原request_id与实际业务结果，禁止盲目重放提交、上传或点击 |
| RELEASING / QUARANTINED | 用原令牌查原租约；清理未知交维护者按Hub离线核查流程处理，不修改历史UNKNOWN或抢占 |

完整合同见[Node使用权租约接口](../reference/Node使用权租约接口.md)，升级和核查见[运行与排障](../deployment/运行与排障.md)。
