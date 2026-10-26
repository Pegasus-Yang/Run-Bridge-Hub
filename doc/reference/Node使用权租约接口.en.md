# Node lease API

[简体中文](Node使用权租约接口.md) · English

Applies to **Hub 0.9.3 / Node 0.8.2**. Hub has no user-account system. `hub_token` queries the pool and claims a whole Node; each claim issues an independent `access_token` for execution, renewal, and release. Put tokens in `Authorization: Bearer ...`, never a URL.

## 1. Query before claiming

`GET /v1/pool/nodes` uses the Hub token and returns `{"nodes": [...]}`. Each NodeView adds `lease`, with state `UNCLAIMED`, `HELD`, `RELEASING`, or `QUARANTINED`, and `claimable`. Resource occupancy and whole-Node ownership are separate.

`GET /v1/pool/nodes/{node_id}/tools` uses the Hub token and returns `{"node": {...}, "tools": [...]}`. Tool declarations share their source with MCP `tools/list`, including `name`, `description`, `inputSchema`, and `annotations`. This prepares plans without issuing a lease or starting a browser. Disabled MCP returns 503 `MCP_DISABLED`.

## 2. Claim

`POST /v1/nodes/{node_id}/grants` uses the Hub token:

```json
{"request_id":"claim_unique_batch_id","lease_seconds":3600}
```

`request_id` is required and follows the Identifier format: 1–128 characters, starting with an ASCII letter/digit, followed by letters, digits, underscores, or hyphens. Optional `lease_seconds` must be a positive integer; the default is `min(3600, grant_max_lease_seconds)`. An explicit excessive value returns 422 `LEASE_TOO_LONG`. Hub defaults are maximum 86400 seconds and idle reclaim 600 seconds.

First success returns 201, for example:

```json
{
  "grant_id":"grant_example", "node_id":"node_a", "state":"HELD",
  "created_at":"2026-10-23T00:00:00+00:00",
  "expires_at":"2026-10-23T01:00:00+00:00",
  "last_activity_at":"2026-10-23T00:00:00+00:00",
  "idle_timeout_seconds":600, "idle_deadline_at":"2026-10-23T00:10:00+00:00",
  "inflight":false, "released_at":null, "close_reason":null, "cleanup":"COMPLETE",
  "token_available":true, "access_token":"EXAMPLE_ONLY_LEASE_TOKEN",
  "access_config":{
    "hub_url":"https://hub.example/runbridge", "node_id":"node_a",
    "grant_id":"grant_example", "access_token":"EXAMPLE_ONLY_LEASE_TOKEN",
    "expires_at":"2026-10-23T01:00:00+00:00"
  }
}
```

These are illustrative values, not usable credentials. `cleanup` is `COMPLETE`, `PENDING`, or `UNKNOWN` for sessions created so far; COMPLETE while HELD does not return Node. While `inflight=true`, `idle_deadline_at=null`; hard `expires_at` still applies.

For the same Node + request ID and matching input, a duplicate returns 200 containing only `grant_id`, `node_id`, `state`, `token_available=false`. Secrets are not returned again. Different input returns 409 `REQUEST_ID_CONFLICT`. Ended claims are not revived. If the first response is lost, wait for reclaim before making a new claim.

Other 409 errors: `NODE_LEASE_BUSY` for occupied/releasing/quarantined Node, `NODE_OFFLINE`, `NODE_NOT_READY` for no usable capability, and `NODE_CLEANUP_REQUIRED` for unresolved prior execution.

## 3. Status, renewal, and release

Use the original lease's access token, not a Hub or device token:

| Endpoint | Input | Output |
| --- | --- | --- |
| `GET /v1/grants/{grant_id}` | None | Lease state fields, without `access_token`, `access_config`, or `token_available` |
| `POST /v1/grants/{grant_id}/renew` | `{"lease_seconds":3600}`, field optional | State; expiry becomes max(original expiry, now + requested duration), without resetting idle time |
| `DELETE /v1/grants/{grant_id}` | None | State; 202 for RELEASING, otherwise 200 |

Release immediately prevents further execution and renewal. After all original sessions confirm COMPLETE, ownership becomes RELEASED. Unknown cleanup becomes QUARANTINED and blocks a new claim. Expiry and idle reclaim use the same cleanup path, with `close_reason` `LEASE_EXPIRED` and `IDLE_TIMEOUT`; holder release uses `RELEASED_BY_HOLDER`.

The old token can query its original lease or repeat release after invalidation, but cannot execute, renew, or affect a successor lease. Poll to RELEASED or QUARANTINED and retain the actual outcome. Mismatched tokens return 401 `INVALID_ACCESS_TOKEN`; a grant outside a valid token returns 403 `GRANT_OUTSIDE_TOKEN`. Execution/renewal on an invalid lease returns 401.

## 4. Access files and DSH lifecycle

Save `access_config` as exactly five fields: `hub_url`, `node_id`, `grant_id`, `access_token`, `expires_at`. Hub's `public_url`, including any reverse-proxy prefix, determines the exported URL. Missing configuration returns 503 `PUBLIC_URL_REQUIRED`; it is not inferred from an arbitrary request Host.

Hub auto-claim mode uses a separate file:

```yaml
hub_url: https://hub.example/runbridge
hub_token: REPLACE_WITH_PRIVATE_HUB_TOKEN
```

DSH explicitly chooses Hub auto-claim or an existing access file. Auto-claim reads the tool directory and prepares/reviews plans before claiming. API-only tests do not claim Node. A CSV batch shares one Node lease, closes each case's browser, and releases Node on completion, cancellation, or failure before finalizing the report. Polling, renewal, frames, and MCP handshakes do not reset idle time.

Node `grant` / `revoke` are removed; old owner-list/revocation endpoints return 410. `node_token` is for device control/execution/upload authentication. Browser sessions separately allow `lease_seconds` 1–3600.

Without `hub_token_file` or `RUNBRIDGE_HUB_TOKEN`, pool/claim calls return 503 `HUB_ACCESS_NOT_CONFIGURED`; enrollment and monitoring remain available. Explicit missing/empty credential files fail startup.

Optional `resolution` is normally null. Offline maintainer review can release occupancy while preserving `cleanup=UNKNOWN` and recording evidence in `resolution`; this does not mean Node reported COMPLETE. Follow [operations](../deployment/运行与排障.en.md); ordinary Hub authentication cannot perform that maintenance.
