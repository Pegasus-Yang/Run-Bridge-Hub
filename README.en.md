# RunBridge Hub

**Give programs and agents access to browsers on remote devices through HTTP / MCP.**

[简体中文](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/README.md) · English · [Quick start](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/README.en.md#quick-start) · [Documentation](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/README.en.md) · [Changelog (Chinese)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/project/%E7%89%88%E6%9C%AC%E5%8F%91%E5%B8%83%E8%AE%B0%E5%BD%95.md) · [Issues](https://github.com/Pegasus-Yang/Run-Bridge-Hub/issues)

[![Python 3.14](https://img.shields.io/badge/Python-3.14-3776AB?style=flat-square&logo=python&logoColor=white)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/pyproject.toml) [![MIT](https://img.shields.io/badge/License-MIT-16a34a?style=flat-square)](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/LICENSE)

RunBridge Hub is the server component of RunBridge. It accepts connections from [RunBridge Node](https://github.com/Pegasus-Yang/Run-Bridge-Node/blob/main/README.en.md), allocates exclusive device leases, manages browser sessions, and routes commands and results. Clients use HTTP or MCP without connecting directly to the Node's browser port.

Use it for automation programs, agent tools, and test teams that need to share browser devices. Browsers, Playwright, and page objects stay on Node devices; Hub itself needs only a Python environment.

## Highlights

| Capability | What you can do |
| --- | --- |
| Shared HTTP and MCP entry | Use the same authorization, sessions, and execution flow from programs and agents |
| Remote browser operations | Let Nodes connect to Hub and access their browsers through one gateway |
| Exclusive Node leases | Claim, renew, and release an entire Node; reclaim expired or idle leases without overlapping ownership |
| Queryable results | Deduplicate requests and recover their original status after timeouts or disconnections |
| Page streaming | Observe the same page being operated on using frames captured by Node |
| Read-only dashboard | Search and filter devices; inspect connections, occupancy, capabilities, heartbeats, and measured control-channel RTT |

## Screenshots

The dashboard brings device connections, resource occupancy, and capabilities together, on desktop and mobile. Open a node for details. Dashboard access uses its own read-only token.

![RunBridge Hub dashboard with connection states, resource occupancy, capabilities, and measured RTT](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/design/assets/node-dashboard/%E5%A4%A9%E8%93%9D%E4%B8%BB%E9%A2%98%E6%A1%8C%E9%9D%A2.jpg?raw=true)

This screenshot shows a local acceptance environment at the time of capture, using the Chinese UI. Your dashboard displays the connected Hub's actual state. See the [dashboard guide](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%8A%82%E7%82%B9%E6%80%BB%E8%A7%88.en.md) for field definitions.

## How it works

![RunBridge Hub architecture](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/architecture/assets/hub-overview.en.svg?raw=true)

Deploy Hub and Node separately: Hub provides the service entry, and Node executes on the browser device. Each has its own configuration, identity, and runtime environment.

## Quick start

Hub **0.9.3** is available on [PyPI](https://pypi.org/project/runbridge-hub/0.9.3/). Install it with the commands below, or download wheels from [GitHub Releases](https://github.com/Pegasus-Yang/Run-Bridge-Hub/releases) and follow the [separate-directory installation guide](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.en.md). A source installation route is also provided below.

### Install from PyPI

Run in a new deployment directory with Python 3.14 and uv. With this installation, continue at step 2. HTTP-only users may omit `[mcp]`.

Mirrors may lag behind the first release. If the Aliyun mirror below does not yet list this version, download its wheel from [PyPI files](https://pypi.org/project/runbridge-hub/0.9.3/#files) and follow the separate-directory installation guide.

```bash
mkdir -p ~/runbridge-hub
cd ~/runbridge-hub
uv venv --python 3.14 .venv
uv pip install --python .venv/bin/python "runbridge-hub[mcp]==0.9.3" -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/runbridge-hub generate-token --output .runbridge/enrollment.token
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

### 1. Install Hub

On the **Hub machine**, prepare Git, Python **3.14.x**, and [uv](https://docs.astral.sh/uv/getting-started/installation/). These commands use a macOS / Linux shell:

```bash
git clone https://github.com/Pegasus-Yang/Run-Bridge-Hub.git
cd Run-Bridge-Hub
uv sync --locked --no-dev -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
.venv/bin/runbridge-hub generate-token --output .runbridge/enrollment.token
.venv/bin/runbridge-hub generate-token --output .runbridge/hub.token
```

`uv` creates `.venv` at the repository root. The two credentials serve different roles: **Node enrollment** and **client claims**. For installation from a wheel in a separate directory, see [deployment](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/deployment/%E9%83%A8%E7%BD%B2%E4%B8%8E%E8%BF%90%E8%A1%8C.en.md).

### 2. Save configuration and start Hub

Create `hub.yaml` in the current installation directory. Replace `public_url` with the **Hub base URL reachable from both Node and clients**:

```yaml
host: 0.0.0.0
enrollment_token_file: .runbridge/enrollment.token
hub_token_file: .runbridge/hub.token
public_url: http://hub.example:8787
```

```bash
.venv/bin/runbridge-hub serve --settings hub.yaml
```

Leave that terminal running and check from another terminal:

```bash
curl --fail http://127.0.0.1:8787/health
```

Expect `{"status":"ok","protocol_version":2}`. Open the `Dashboard URL` from the startup log. An empty list is normal before devices enroll. Keep credential files and dashboard links containing the read-only token private.

For a source installation, add the optional MCP dependency below. The PyPI command above already includes this extra:

```bash
uv sync --locked --no-dev --extra mcp -i http://mirrors.aliyun.com/pypi/simple/ --trusted-host mirrors.aliyun.com
```

Add `mcp_enabled: true` to `hub.yaml` and restart. Agents connect using Streamable HTTP at the actual Hub base URL plus `/mcp`. See [MCP integration](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/MCP%E6%B5%8F%E8%A7%88%E5%99%A8%E6%8E%A5%E5%85%A5.en.md) for authentication and tool usage.

### 3. Connect Node and verify a browser operation

Privately give the Hub URL and original `enrollment.token` to the device maintainer, who follows the [Node quick start](https://github.com/Pegasus-Yang/Run-Bridge-Node/blob/main/README.en.md#quick-start). Separately provide `hub.token` to the client. Follow the [client guide](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%B0%83%E7%94%A8%E6%96%B9%E5%AF%B9%E6%8E%A5%E4%B8%8E%E4%BD%BF%E7%94%A8.en.md) to claim Node and save the returned configuration as `.runbridge/access.json`.

Source installations already include the examples. For PyPI or wheel installations, first download both standard-library scripts into the same paths in your deployment directory:

```bash
mkdir -p doc/reference/examples
curl --fail --location https://raw.githubusercontent.com/Pegasus-Yang/Run-Bridge-Hub/main/doc/reference/examples/%E6%89%A7%E8%A1%8C%E4%BC%9A%E8%AF%9D%E8%B0%83%E7%94%A8.py --output doc/reference/examples/执行会话调用.py
curl --fail --location https://raw.githubusercontent.com/Pegasus-Yang/Run-Bridge-Hub/main/doc/reference/examples/node_lease.py --output doc/reference/examples/node_lease.py
```

Run the example to open a page, read its title, save a PNG, close the browser session, and return Node:

```bash
.venv/bin/python doc/reference/examples/执行会话调用.py --access-file .runbridge/access.json --resource-id chromium --url https://example.com --screenshot .runbridge/page.png
.venv/bin/python doc/reference/examples/node_lease.py release --access-file .runbridge/access.json
```

Use the actual resource ID advertised by Node. The URL must be reachable from the **Node device**. Check the screenshot, `cleanup=COMPLETE`, and lease state `RELEASED`. The [quick-start guide](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.en.md) includes a complete check using Hub's own health page instead of an external website.

## Supported scope

- Current Hub: **0.9.3**, paired with Node **0.8.2**. Python **3.14.x** is required. Hub does not need browsers, Playwright, or Node.js installed.
- **33 project methods and 27 MCP tools** are available. The interface borrows Playwright naming; the [method reference](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/Playwright%E6%96%B9%E6%B3%95%E8%A1%A8.en.md) defines the supported subset. Direct official SDK connections, arbitrary scripts, and SDK callbacks are outside this interface.
- Managed browsers support HTTP / MCP; borrowed Chrome uses HTTP. Frames provide observation; clients verify the business outcome.
- Browser sessions and Node leases are released separately. Return Node after the batch even when the browser is closed. Unknown cleanup keeps the resource quarantined; see [leases](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/Node%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%8E%A5%E5%8F%A3.en.md).
- Dashboard labels and some CLI messages remain Chinese. English documentation does not change runtime language.

## Documentation and help

| Start here | Contents |
| --- | --- |
| [Documentation index](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/README.en.md) | Reading paths for deployers, clients, and maintainers |
| [Quick start](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E5%BF%AB%E9%80%9F%E5%BC%80%E5%A7%8B.en.md) · [Deployment](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/deployment/%E9%83%A8%E7%BD%B2%E4%B8%8E%E8%BF%90%E8%A1%8C.en.md) | Installation, configuration, startup, checks, handoff, and backups |
| [Parameters](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/%E5%8F%82%E6%95%B0%E8%AF%A6%E8%A7%A3.en.md) · [Annotated YAML](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/examples/Hub%E5%90%AF%E5%8A%A8%E9%85%8D%E7%BD%AE.en.yaml) | Options, defaults, paths, and deployment scenarios |
| [Client guide](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%B0%83%E7%94%A8%E6%96%B9%E5%AF%B9%E6%8E%A5%E4%B8%8E%E4%BD%BF%E7%94%A8.en.md) · [Lease API](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/reference/Node%E4%BD%BF%E7%94%A8%E6%9D%83%E7%A7%9F%E7%BA%A6%E6%8E%A5%E5%8F%A3.en.md) | Claim devices, operate pages, query results, and release resources |
| [MCP integration](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/MCP%E6%B5%8F%E8%A7%88%E5%99%A8%E6%8E%A5%E5%85%A5.en.md) · [DSH integration](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/DSH-Test-Plugin%E5%AF%B9%E6%8E%A5%E6%8C%87%E5%8D%97.en.md) | Agent tools, plugin settings, and batch lifecycle |
| [Page streaming](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E6%B5%8F%E8%A7%88%E5%99%A8%E7%94%BB%E9%9D%A2%E6%B5%81%E6%8E%A5%E5%85%A5.en.md) · [Dashboard](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/user-guide/%E8%8A%82%E7%82%B9%E6%80%BB%E8%A7%88.en.md) | Observe pages and devices |
| [Operations and troubleshooting](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/doc/deployment/%E8%BF%90%E8%A1%8C%E4%B8%8E%E6%8E%92%E9%9A%9C.en.md) | Errors, upgrades, unknown cleanup, and offline review |

## Development and contributions

Use [Issues](https://github.com/Pegasus-Yang/Run-Bridge-Hub/issues) or submit a Pull Request. Include both component versions, environment, reproduction steps, and redacted error details.

Development uses the root `.venv`. The [contribution guide](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/CONTRIBUTING.en.md) explains setup and validation and links to the detailed development manual in Chinese. Maintained by [Pegasus-Yang](https://github.com/Pegasus-Yang).

## License

This project uses the [MIT License](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/LICENSE). Bundled [Phosphor Icons](https://github.com/phosphor-icons/core) retain their [original MIT license](https://github.com/Pegasus-Yang/Run-Bridge-Hub/blob/main/src/runbridge_hub/web/icons/LICENSE) and copyright notice. Other dependencies keep their respective licenses.
