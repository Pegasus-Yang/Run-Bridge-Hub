# Node 使用权租约接口

适用版本：Hub 0.9.2、Node 0.8.1。

Hub 不维护用户。`hub_token` 用于查看资源池和申请整个 Node；每次领取产生独立的 `access_token`，只有其持有者可以执行、续租和释放这份使用权。所有令牌放在 `Authorization: Bearer ...`，不得放在 URL。

## 1. 领取前查询

`GET /v1/pool/nodes` 使用 Hub 令牌，返回 `{"nodes": [...]}`。每个节点保留原 NodeView 字段，并增加 `lease`：`state` 为 `UNCLAIMED/HELD/RELEASING/QUARANTINED`，`claimable` 表示当前是否可领取。资源自身的 occupancy 与整 Node 租约状态分开。

`GET /v1/pool/nodes/{node_id}/tools` 使用 Hub 令牌，返回 `{"node": {...}, "tools": [...]}`。`tools` 是与 MCP tools/list 同源的 MCP 工具声明，每项含 `name/description/inputSchema/annotations` 等标准字段，供领取前准备计划；不签发租约，不启动浏览器。MCP 未启用时返回 503 `MCP_DISABLED`。

## 2. 申请

`POST /v1/nodes/{node_id}/grants` 使用 Hub 令牌：

```json
{"request_id":"claim_unique_batch_id","lease_seconds":3600}
```

`request_id` 必填，遵循现有 Identifier（1～128 位字母、数字、下划线、短横线）。`lease_seconds` 可省略，必须是正整数，默认 `min(3600, grant_max_lease_seconds)`；显式超限返回 422 `LEASE_TOO_LONG`。默认上限 86400 秒，默认空闲回收 600 秒，均由 Hub YAML 配置。

首次成功返回 201：

```json
{
  "grant_id":"grant_...", "node_id":"node_a", "state":"HELD",
  "created_at":"2026-10-23T00:00:00+00:00",
  "expires_at":"2026-10-23T01:00:00+00:00",
  "last_activity_at":"2026-10-23T00:00:00+00:00",
  "idle_timeout_seconds":600, "idle_deadline_at":"2026-10-23T00:10:00+00:00",
  "inflight":false, "released_at":null, "close_reason":null, "cleanup":"COMPLETE",
  "token_available":true, "access_token":"本次随机令牌",
  "access_config":{
    "hub_url":"https://hub.example/runbridge", "node_id":"node_a",
    "grant_id":"grant_...", "access_token":"本次随机令牌",
    "expires_at":"2026-10-23T01:00:00+00:00"
  }
}
```

`cleanup` 描述当前已创建会话的清理结果：`COMPLETE/PENDING/UNKNOWN`。HELD 的 COMPLETE 也不表示 Node 已交还。`inflight=true` 时 `idle_deadline_at=null`，硬性 `expires_at` 仍生效。

同一 Node + request_id 重复请求，相同输入返回 200，**仅**含 `grant_id/node_id/state/token_available=false`，不再返回任何原始秘密；不同输入返回 409 `REQUEST_ID_CONFLICT`。已结束的请求不复活。首次响应遗失时等待空闲回收，再以新 request_id 领取。

占用返回 409 `NODE_LEASE_BUSY`；离线返回 409 `NODE_OFFLINE`；无有效可用能力返回 409 `NODE_NOT_READY`；遗留执行未确认清理返回 409 `NODE_CLEANUP_REQUIRED`。

## 3. 状态、续租与释放

以下接口只接受原租约的 access_token，Hub 令牌和 node_token 均不能代替。

| 接口 | 输入 | 输出 |
| --- | --- | --- |
| `GET /v1/grants/{grant_id}` | 无 | 上述租约状态字段，不含 access_token、access_config、token_available |
| `POST /v1/grants/{grant_id}/renew` | `{"lease_seconds":3600}`，可省略该字段 | 租约状态；期限为 max(原期限, 当前时间加申请时长)，不刷新空闲期限 |
| `DELETE /v1/grants/{grant_id}` | 无 | 租约状态；RELEASING 返回 202，其他状态返回 200 |

释放立即禁止旧令牌执行及续租。确认所有原会话 cleanup=COMPLETE 后状态为 RELEASED；未知清理为 QUARANTINED，仍阻止再次领取。租期到期与空闲回收走同一路径，close_reason 分别为 LEASE_EXPIRED、IDLE_TIMEOUT，主动释放为 RELEASED_BY_HOLDER。

旧令牌在到期后仍可查询**原租约**或重复释放，不能执行、续租或影响新租约。调用方应轮询原状态至 RELEASED 或 QUARANTINED，记录实际结果。QUARANTINED 应报告设备待维护，禁止自动抢占。令牌不匹配返回 401 INVALID_ACCESS_TOKEN；匹配但 grant_id 不属于该令牌返回 403 GRANT_OUTSIDE_TOKEN；租约无效时执行及续租返回 401 INVALID_ACCESS_TOKEN。

## 4. 访问文件与 DSH 生命周期

执行访问文件严格保留五个字段：`hub_url/node_id/grant_id/access_token/expires_at`，保存领取响应的 `access_config` 即可。Hub 的 `public_url` 决定导出基址，支持反向代理路径前缀；未配置时申请返回 503 PUBLIC_URL_REQUIRED，避免从任意请求 Host 导出错误地址。

Hub 自动申请模式另用独立文件：

```yaml
hub_url: https://hub.example/runbridge
hub_token: 私有Hub申请令牌
```

DSH 明确选择 Hub 自动申请模式或已有访问文件模式。使用 Hub 模式时，先用 pool 工具声明生成并审核计划，再领取；纯 API 测试不领取。整批 CSV 共用一份 Node 租约，逐用例关闭浏览器，整批结束、取消或失败时收尾并释放，等待和记录实际释放状态后封存报告。状态轮询、续租、画面和 MCP 握手不刷新空闲计时。

旧 Node grant/revoke 管理命令已移除，旧所有者列表和撤销接口返回410；node_token仅用于设备登记后的控制、执行连接及画面上传认证。浏览器会话自身lease_seconds仍为1～3600秒，不能当作Node租期传递。

Hub未配置hub_token_file或RUNBRIDGE_HUB_TOKEN时，资源池与申请返回503 HUB_ACCESS_NOT_CONFIGURED；此时只运行设备登记与监控，不允许领取。显式凭据文件缺失/为空时启动失败。

状态另含可选resolution（通常为null），只在本地停机核查后携带人工证据。经核查解除占用时，原cleanup=UNKNOWN保持不变，state可以为RELEASED，resolution说明依据；这不表示Node报告过COMPLETE。普通Hub认证不能进行此操作，步骤见[运行与排障](../deployment/运行与排障.md)。
