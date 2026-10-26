# DSH-Test-Plugin integration

[简体中文](DSH-Test-Plugin对接指南.md) · English

Applies to **Hub 0.9.3, Node 0.8.2, and DSH-Test-Plugin 0.15.0**. The plugin uses Hub MCP to execute browser tests on Node. The DSH host needs neither the remote browser nor Python Playwright.

Flow: configure Hub claim credentials → enroll Node and advertise capabilities → read private Hub authentication and prepare/review a plan → claim Node → execute the batch → close browsers and return Node → finalize the report. A Hub credential can claim an available Node; subsequent operations use that claim's token.

## 1. Prepare each role

| Role | Preparation | Handoff |
| --- | --- | --- |
| Hub deployer | Install 0.9.3, enable MCP, configure `public_url` and independent `hub_token_file` | Enrollment attachment to Node; base URL and separate claim credential to clients |
| Node maintainer | Install 0.8.2, keep a managed Playwright resource online, pass real browser probing | Node ID, resource ID, mode, and version; no client access-file issuance |
| DSH user | Install plugin 0.15.0, keep private credentials on the actual DSH host, configure the correct profile | Settings, cases, expectations, reports, and cleanup outcomes |

On Hub, generate a separate claim file if one does not already exist:

```bash
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

Extend the existing enrollment YAML and restart normally:

```yaml
hub_token_file: .runbridge/hub.token
public_url: http://hub.example:8787  # Actual reachable URL; proxy prefix allowed.
mcp_enabled: true
grant_max_lease_seconds: 86400
grant_idle_timeout_seconds: 600
```

`mcp_allowed_hosts` omitted or `[]` permits any Host; configure a nonempty list only for restrictions. Claim text is 32–256 single-line characters, separate from enrollment and dashboard tokens. It cannot execute MCP directly and is not needed by the Node process. See [quick start](快速开始.en.md) and [parameters](../reference/参数详解.en.md).

Check ONLINE, fresh capabilities, and MANAGED_CHROMIUM resource READY/FREE in the pool/dashboard. MCP `browser_start` currently selects managed; borrowed Chrome uses HTTP.

## 2. Choose the credential source

| Source | Use case | Private file |
| --- | --- | --- |
| Hub auto-claim (recommended) | Claim for each batch and return afterward | Only `hub_url` and `hub_token` |
| Existing access file | Give an explicitly claimed Node lease to this batch | `hub_url`, `node_id`, `grant_id`, `access_token`, `expires_at` |

### Hub authentication file

On the **actual DSH host**, save `hub-auth.yaml` (JSON with the same fields also works):

```yaml
hub_url: "http://hub.example:8787"
hub_token: "REPLACE_WITH_ACTUAL_HUB_CLAIM_TOKEN"
```

| Parameter | Source and requirement |
| --- | --- |
| `hub_url` | Hub deployer; actual `public_url`/proxy base, without credentials/query/fragment or `/health`, `/v1`, `/v2`, `/mcp` suffix |
| `hub_token` | Original separate `hub.token`; no `Bearer ` or `token=` prefix |
| Target `nodeId` | Startup log, nonsecret identity ID, or `GET /v1/pool/nodes`; stable ID, not name/IP/resource |
| `resourceId` | Actual managed capability, usually `chromium` |

The pool never exposes someone else's access token. Token possession authorizes its role; Hub does not create user accounts.

### Existing access file

Claim via `POST /v1/nodes/{node_id}/grants`, using a unique request ID and optional duration. Save the response's **access_config**, not the entire response, as private JSON/YAML. The [claim helper](../reference/examples/node_lease.py) and [client guide](调用方对接与使用.en.md) show how. Node `grant` / `revoke` are removed.

```yaml
hub_url: "http://hub.example:8787"
node_id: "node_example"
grant_id: "grant_example"
access_token: "REPLACE_WITH_ACTUAL_ISSUED_LEASE_TOKEN"
expires_at: "2030-01-01T01:00:00Z"  # Keep the actual issued timestamp, not this example.
```

`hub_url` comes from Hub's exported URL, `node_id` from the claimed device, and `grant_id` / `access_token` / `expires_at` from that claim. Keep them paired. Editing local expiry does not renew a lease; tokens cannot be recovered from hashes, the dashboard, or shared Hub credentials.

The plugin requires the first four fields; current Hub always exports all five and no permanent leases. Preserve the complete `access_config`. After the first response, duplicate requests return `token_available=false` without the secret. If the first response is lost, retain claim records and await reclaim before a new request.

The plugin releases this exclusive whole-Node lease at batch end. Do not share its token with another active task. A later batch needs a new lease after release.

## 3. Read, check, and save DSH settings

In the actual test profile, open **Settings → 测试插件 → 浏览器设置** (Test plugin → Browser settings), choose remote RunBridge MCP, and explicitly select a connection source. Actual UI labels may remain Chinese.

| Field | Hub mode | Existing-file mode |
| --- | --- | --- |
| `backend` | `runbridge` | `runbridge` |
| `connectionSource` | `hub` | `access-file` |
| `hubFile` | Host path to Hub auth YAML/JSON | Unused |
| `nodeId` | Target Node ID from pool | Read from access file |
| `accessFile` | Private execution file managed by this batch | Already claimed access YAML/JSON |
| `resourceId` | Actual managed resource, usually `chromium` | Same |
| `nodeLeaseSeconds` | Omit for Hub default 3600 or set a positive integer | Existing lease's original duration/state |
| `leaseSeconds` | Browser session lease, plugin default 1800, range 1–3600 | Same |
| `previewEnabled` | Optional actual frames | Same |

Settings save to `browserConnection`; static profile browser settings support the same fields. The plugin's [remote guide (Chinese)](https://github.com/Pegasus-Yang/DSH-Test-Plugin/blob/main/doc/user-guide/RunBridge远程浏览器与持续预览.md) covers its current UI. Keep secrets in private files rather than profiles.

1. Enter a file path readable by the DSH host. Prefer absolute paths; no `~` or `$HOME`. Relative paths use the current workspace, not the web browser's computer.
2. Select **读取配置** (Read configuration) and check the redacted summary. Hub mode does not require manually supplied grant/access tokens.
3. Enter actual Node/resource IDs and run the connection check. Hub mode reads pool/tool declarations without claiming Node or starting a browser. Existing-file mode checks the held lease, MCP tools, and resource without starting a browser.
4. Set durations and preview as needed, then save. Changes apply to the next batch; an active run keeps its original connection.

Use mode 600 files inside mode 700 directories. Keep credentials out of Git, cases, prompts, and reports. The plugin saves paths/preferences, reads originals on the host, and privately manages auto-issued execution files. Re-read/check after changing source, file, or device. Profile overlays are managed by the actual DSH administrator.

A parsed file proves format; a successful check proves availability at that time. Another client may claim Node before execution; the atomic claim remains authoritative.

## 4. Run the first browser test

Replace the URL with Hub's health page reachable by the **Node browser**, then enter in DSH:

```text
/test-plan Open http://hub.example:8787/health in the browser, assert that the page body contains status, ok, and protocol_version, save a screenshot, then close the browser and return this batch's Node lease.
```

Approve the plan to execute. `/test` runs directly; `/test-run cases.md` reads workspace file cases; `/test-data data.csv --file cases.md` expands parameters. See [plugin usage](https://github.com/Pegasus-Yang/DSH-Test-Plugin/blob/main/doc/user-guide/使用说明.en.md).

Hub mode prepares/reviews from the read-only directory before claiming; API-only cases do not claim. A CSV batch shares one Node lease and closes each case's browser, returning Node after the batch. Use real returned session/page IDs, without model-supplied secrets or local CDP endpoints.

Verify actual body text, assertions, screenshot, `cleanup=COMPLETE`, and Node `RELEASED`. Success, cancellation, and failure all await cleanup/release before finalizing the report. Unknown release records failure/quarantine; sending DELETE alone is not confirmation.

The health-page test must actually use a browser. Browser requests originate on Node; API-only requests originate on the DSH host. Verify those networks separately. Business tests also check final page/business records; HTTP 200 or a model summary is not a business assertion.

## 5. Duration, idle time, and release

Default Node lease: 3600 seconds. Explicit positive duration is bounded by Hub `grant_max_lease_seconds` (default 86400). `grant_idle_timeout_seconds` defaults to 600. Browser sessions separately allow 1–3600 seconds.

Session creation, page actions, DOM reads, and screenshots count as use. Valid bounded in-flight execution pauses idle counting; completion restarts it. MCP handshakes, tools/list, inspection/status, polling, frames, heartbeats, and renewal do not reset idle time. An open browser can still be reclaimed.

Renewal uses the original token, does not extend an existing browser session, and cannot revive an invalid lease. Close sessions, release Node, and await RELEASED. QUARANTINED blocks new claims. An invalidated token may query its original terminal state/repeat release, not take over a successor.

Preview follows the session's returned visual path and same Page. Clear stale/ended images. Remote mode supplies PNG preview/report screenshots, not remote recording; see [streaming](浏览器画面流接入.en.md).

## 6. Troubleshooting

| Symptom | Action |
| --- | --- |
| File read/parse failure | Actual host path, permissions, selected source, and correct two-field vs five-field schema |
| HUB_ACCESS_NOT_CONFIGURED / PUBLIC_URL_REQUIRED | Hub deployer configures the independent claim credential/base URL and restarts |
| Claim 401 | Correct Hub credential role, not enrollment/device/dashboard/lease token |
| NODE_LEASE_BUSY | Await original return; no request-ID-based takeover or reservation |
| Offline/not ready | Original process, network, heartbeat, and actual Playwright/Chromium probe |
| Execution/renewal 401 | Original lease expiry, idle/release cause; do not change token to repeat prior effects |
| Unknown claim/no first token | Preserve batch claim records and await reclaim |
| LEASE_TOO_LONG | Lower the requested Node duration or have the deployer change policy |
| MCP 421 / 403 | Nonempty Host list; Origin and resource/session ownership |
| OUTCOME_UNKNOWN | Query original request and actual business outcome before any replay |
| RELEASING / QUARANTINED | Query original lease with original token; maintainer follows offline cleanup review |

See [lease API](../reference/Node使用权租约接口.en.md) and [operations](../deployment/运行与排障.en.md) for full contracts and review.
