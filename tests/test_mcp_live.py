"""显式启用的真实 MCP → Hub → Node → Chromium 验收。"""

import asyncio
import base64
import hashlib
import json
import os
import secrets
import shlex
import socket
import struct
import sys
import subprocess
import threading
import time
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx
import pytest

pytest.importorskip("mcp")

import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


pytestmark = [
    pytest.mark.browser,
    pytest.mark.skipif(
        os.environ.get("RUNBRIDGE_RUN_BROWSER_TESTS") != "1",
        reason="真实浏览器验收需显式设置 RUNBRIDGE_RUN_BROWSER_TESTS=1",
    ),
]
HUB = Path(sys.executable).parents[2]
NODE = Path(os.environ.get("RUNBRIDGE_NODE_ENV", HUB.parent / "node"))
BROWSERS = os.environ.get("PLAYWRIGHT_BROWSERS_PATH")


class Runtime:
    """所有凭据、数据和进程均由此隔离测试创建。"""

    def __init__(self, *, directory: Path):
        self.directory = directory
        self.processes = []
        self.credentials = []
        self.temporary_directories: set[Path] = set()
        self.http = httpx.Client(trust_env=False, timeout=15)
        self.environment = {
            key: value
            for key, value in os.environ.items()
            if key
            not in {
                "VIRTUAL_ENV",
                "RUNBRIDGE_ENROLLMENT_TOKEN",
                "RUNBRIDGE_ACCESS_TOKEN",
            }
        }
        with socket.socket() as reserve:
            reserve.bind(("127.0.0.1", 0))
            self.port = reserve.getsockname()[1]
        self.url = f"http://127.0.0.1:{self.port}"
        self.enrollment = secrets.token_urlsafe(48)
        self.credentials.append(self.enrollment)
        self.enrollment_file = directory / "enrollment.token"
        self.enrollment_file.write_text(self.enrollment)
        self.enrollment_file.chmod(0o600)

    def executable(self, *, project: Path, name: str) -> str:
        return str(
            project
            / ".venv"
            / ("Scripts" if os.name == "nt" else "bin")
            / (f"{name}.exe" if os.name == "nt" else name)
        )

    def spawn(self, *, project: Path, name: str, args: list[str]):
        with (self.directory / f"{name}.log").open(mode="a") as output:
            process = subprocess.Popen(
                [self.executable(project=project, name=name), *args],
                cwd=self.directory,
                env=self.environment,
                stdout=output,
                stderr=subprocess.STDOUT,
            )
        self.processes.append(process)
        return process

    def start(self):
        self.hub = self.spawn(
            project=HUB,
            name="runbridge-hub",
            args=[
                "serve",
                "--port",
                str(self.port),
                "--enable-mcp",
                "--db-path",
                str(self.directory / "hub.sqlite3"),
                "--enrollment-token-file",
                str(self.enrollment_file),
                "--heartbeat-interval",
                "0.1",
                "--heartbeat-timeout",
                "5",
            ],
        )
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            if self.hub.poll() is not None:
                raise AssertionError("隔离 Hub 启动失败，请检查测试目录的脱敏日志")
            try:
                if (
                    self.http.get(url=f"{self.url}/health", timeout=0.3).status_code
                    == 200
                ):
                    break
            except httpx.HTTPError:
                pass
            time.sleep(0.05)
        else:
            raise AssertionError("隔离 Hub 未就绪")
        config = self.directory / "node.json"
        self.command(
            args=[
                "register",
                "--hub-url",
                self.url,
                "--name",
                "mcp-live-test",
                "--config",
                str(config),
                "--enrollment-token-file",
                str(self.enrollment_file),
            ]
        )
        self.identity = json.loads(config.read_text())
        self.credentials.append(self.identity["node_token"])
        self.access = self.grant()
        settings_file = self.directory / "node.yaml"
        settings_file.write_text(
            json.dumps(
                {
                    "config_version": 2,
                    "identity_file": str(config),
                    "tools": {
                        "playwright": {
                            "browser_cache_directory": BROWSERS,
                            "launch_options": {"headless": True},
                        }
                    },
                }
            )
        )
        self.node = self.spawn(
            project=NODE,
            name="runbridge-node",
            args=["run", "--settings", str(settings_file)],
        )
        self.wait_free()

    def command(self, *, args: list[str]):
        completed = subprocess.run(
            [self.executable(project=NODE, name="runbridge-node"), *args],
            cwd=self.directory,
            env=self.environment,
            capture_output=True,
            timeout=15,
        )
        if completed.returncode != 0:
            raise AssertionError("隔离 Node CLI 操作失败，未回显可能包含秘密的输入")

    def grant(
        self, *, expires: float | None = None, resources: list[str] | None = None
    ) -> dict:
        response = self.http.post(
            url=f"{self.url}/v1/nodes/{self.identity['node_id']}/grants",
            headers={"Authorization": f"Bearer {self.identity['node_token']}"},
            json={"expires_in_seconds": expires, "resource_ids": resources},
        )
        assert response.status_code == 201
        access = response.json()
        self.credentials.append(access["access_token"])
        return access

    def query(self, *, session_id: str | None = None, access: dict | None = None):
        permission = access or self.access
        path = (
            f"/v2/sessions/{session_id}"
            if session_id
            else f"/v1/nodes/{self.identity['node_id']}"
        )
        return self.http.get(
            url=self.url + path,
            headers={"Authorization": f"Bearer {permission['access_token']}"},
        )

    def wait_free(self):
        deadline = time.monotonic() + 15
        while time.monotonic() < deadline:
            response = self.query()
            if response.status_code == 200:
                view = response.json()
                resources = (view.get("capabilities") or {}).get("resources", [])
                if (
                    view["connection_status"] == "ONLINE"
                    and resources
                    and resources[0]["readiness"] == "READY"
                    and resources[0]["occupancy"] == "FREE"
                ):
                    assert all(not path.exists() for path in self.temporary_directories)
                    return
            time.sleep(0.03)
        raise AssertionError("Node 未达到 READY/FREE 或未清除会话临时目录")

    def browser_pids(self) -> list[int]:
        if os.name != "posix":
            return []
        output = subprocess.check_output(
            ["ps", "-axo", "pid=,ppid=,command="], text=True
        )
        rows = [line.split(maxsplit=2) for line in output.splitlines()]
        processes = {
            int(row[0]): (int(row[1]), row[2]) for row in rows if len(row) == 3
        }
        owned = {process.pid for process in self.processes}
        while True:
            children = {
                pid for pid, (parent, _) in processes.items() if parent in owned
            }
            if children <= owned:
                break
            owned.update(children)
        pids = []
        for pid in owned:
            command = processes.get(pid, (0, ""))[1]
            if "--user-data-dir=" in command and "--type=" not in command:
                profile = next(
                    Path(arg.split("=", 1)[1])
                    for arg in shlex.split(command)
                    if arg.startswith("--user-data-dir=")
                )
                self.temporary_directories.add(profile.parent)
                pids.append(pid)
        return pids

    def check_exited(self, *, pids: list[int]):
        for pid in pids:
            with pytest.raises(ProcessLookupError):
                os.kill(pid, 0)

    def close(self):
        try:
            for process in reversed(self.processes):
                if process.poll() is None:
                    process.terminate()
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=5)
                        raise AssertionError("隔离进程未能正常退出") from None
        finally:
            self.http.close()
        for path in self.directory.glob("*.log"):
            log = path.read_text()
            if any(secret in log for secret in self.credentials):
                raise AssertionError("测试进程日志泄露了凭据，内容已隐藏")
            assert "Traceback" not in log and "ERROR:" not in log, (
                f"测试进程存在未处理异常：{path.name}"
            )


@pytest.fixture(scope="module")
def runtime(tmp_path_factory):
    if not (NODE / ".venv").is_dir():
        pytest.fail("需显式提供 RUNBRIDGE_NODE_ENV 指向独立 Node 环境")
    context = Runtime(directory=tmp_path_factory.mktemp("mcp-live"))
    try:
        context.start()
        yield context
    finally:
        context.close()


@pytest.fixture(scope="module")
def website():
    records = []
    headers = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            html = """<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>MCP 联调</title>
<h1>MCP 联调表单</h1><form><label>用户名<input name="name"></label><button>保存</button></form>
<p role="status" id="result">待提交</p><button type="button">重复按钮</button><button type="button">重复按钮</button>
<label>附件<input type="file" id="files" multiple></label><pre id="file_sizes">[]</pre>
<script>document.querySelector('form').onsubmit=async e=>{e.preventDefault();
let r=await fetch('/save',{method:'POST',body:JSON.stringify({name:document.querySelector('input').value})});
document.querySelector('#result').textContent=(await r.json()).message;};
document.querySelector('#files').onchange=async e=>{
const files=await Promise.all(Array.from(e.target.files,async f=>({name:f.name,size:f.size,
sha256:Array.from(new Uint8Array(await crypto.subtle.digest('SHA-256',await f.arrayBuffer())),b=>b.toString(16).padStart(2,'0')).join('')})));
document.querySelector('#file_sizes').textContent='FILES:'+JSON.stringify(files);};</script></html>""".encode()
            headers.append(dict(self.headers))
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def do_POST(self):
            value = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            records.append(value)
            headers.append(dict(self.headers))
            body = json.dumps(
                {"message": f"已保存：{value['name']}"}, ensure_ascii=False
            ).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield {
            "url": f"http://127.0.0.1:{server.server_port}",
            "records": records,
            "headers": headers,
        }
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@asynccontextmanager
async def agent(*, runtime: Runtime, access: dict | None = None, mode: str = "auto"):
    """官方 MCP SDK 通过 HTTP 访问，不导入 Hub 或 Node 内部实现。"""
    permission = access or runtime.access
    async with httpx2.AsyncClient(
        headers={"Authorization": f"Bearer {permission['access_token']}"},
        timeout=60,
        trust_env=False,
    ) as http:
        transport = streamable_http_client(url=f"{runtime.url}/mcp", http_client=http)
        async with Client(server=transport, mode=mode) as client:
            yield client


async def invoke(*, client, name: str, arguments: dict):
    result = await client.call_tool(name=name, arguments=arguments)
    assert not result.is_error, result.structured_content
    return result.structured_content


def evidence(*, name: str, facts: dict):
    """可选保存不含凭据和页面私有输入的验收事实。"""
    destination = os.environ.get("RUNBRIDGE_MCP_EVIDENCE_FILE")
    if destination:
        path = Path(destination)
        values = json.loads(path.read_text()) if path.exists() else []
        values.append(
            {
                "test": name,
                "checked_at": datetime.now(UTC).isoformat(),
                "status": "PASS",
                "facts": facts,
            }
        )
        path.write_text(json.dumps(values, ensure_ascii=False, indent=2) + "\n")


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.asyncio
async def test_mcp_authorize_start_operate_verify_and_release(runtime, website, mode):
    initial_records = len(website["records"])
    async with agent(runtime=runtime, mode=mode) as client:
        negotiated = client.protocol_version
        assert negotiated == ("2026-07-28" if mode == "auto" else "2025-11-25")
        tools = await client.list_tools()
        assert len(tools.tools) == 27
        node = await invoke(
            client=client,
            name="node_inspect",
            arguments={"node_id": runtime.identity["node_id"]},
        )
        assert node["connection_status"] == "ONLINE"
        started = await invoke(
            client=client, name="browser_start", arguments={"node_id": node["node_id"]}
        )
        ids = {
            "session_id": started["session"]["session_id"],
            "page_id": started["page_id"],
        }
        pids = runtime.browser_pids()
        assert os.name != "posix" or pids
        try:
            assert started["session"]["state"] == "ACTIVE"
            busy = await client.call_tool(
                name="browser_start", arguments={"node_id": node["node_id"]}
            )
            assert busy.is_error and busy.structured_content["code"] == "RESOURCE_BUSY"
            await invoke(
                client=client,
                name="browser_navigate",
                arguments={**ids, "url": website["url"]},
            )
            snapshot = await invoke(
                client=client, name="browser_snapshot", arguments=ids
            )
            assert (
                "MCP 联调表单" in snapshot["snapshot"]
                and "用户名" in snapshot["snapshot"]
            )
            await invoke(
                client=client,
                name="browser_fill",
                arguments={
                    **ids,
                    "target": {"by": "label", "value": "用户名"},
                    "value": f"测试-{mode}",
                },
            )
            read = await invoke(
                client=client,
                name="browser_read",
                arguments={
                    **ids,
                    "target": {"by": "label", "value": "用户名"},
                    "kind": "input_value",
                },
            )
            assert read["value"] == f"测试-{mode}"
            timeout = await client.call_tool(
                name="browser_click",
                arguments={
                    **ids,
                    "target": {"by": "text", "value": "不存在的按钮"},
                    "timeout_ms": 100,
                },
            )
            assert (
                timeout.is_error
                and timeout.structured_content["code"] == "OPERATION_TIMEOUT"
                and timeout.structured_content["execution_outcome"] == "OUTCOME_UNKNOWN"
            )
            ambiguous = await client.call_tool(
                name="browser_click",
                arguments={
                    **ids,
                    "target": {"by": "role", "value": "button", "name": "重复按钮"},
                },
            )
            assert (
                ambiguous.is_error
                and ambiguous.structured_content["code"] == "AMBIGUOUS_TARGET"
            )
            await invoke(
                client=client,
                name="browser_click",
                arguments={
                    **ids,
                    "target": {"by": "role", "value": "button", "name": "保存"},
                },
            )
            await invoke(
                client=client,
                name="browser_wait_for",
                arguments={
                    **ids,
                    "target": {"by": "role", "value": "status"},
                    "state": "text",
                    "value": f"已保存：测试-{mode}",
                },
            )
            saved = await invoke(
                client=client,
                name="browser_read",
                arguments={**ids, "target": {"by": "css", "value": "#result"}},
            )
            assert saved["value"] == f"已保存：测试-{mode}"
            assert website["records"][initial_records:] == [{"name": f"测试-{mode}"}]
            assert all(
                not any(key.lower() == "authorization" for key in item)
                for item in website["headers"]
            )
            screenshot = await client.call_tool(
                name="browser_screenshot", arguments=ids
            )
            assert not screenshot.is_error
            png = base64.b64decode(
                next(item.data for item in screenshot.content if item.type == "image")
            )
            assert png[:8] == b"\x89PNG\r\n\x1a\n" and struct.unpack(
                ">II", png[16:24]
            ) == (1280, 720)
            (runtime.directory / f"page-{mode}.png").write_bytes(png)
            unknown_page = await client.call_tool(
                name="browser_snapshot", arguments={**ids, "page_id": "page_not_owned"}
            )
            assert (
                unknown_page.is_error
                and unknown_page.structured_content["code"] == "PAGE_NOT_FOUND"
            )
        finally:
            stopped = await invoke(
                client=client,
                name="browser_stop",
                arguments={"session_id": ids["session_id"]},
            )
        assert (
            stopped["session"]["state"] == "CLOSED"
            and stopped["session"]["cleanup"] == "COMPLETE"
        )
        repeated = await invoke(
            client=client,
            name="browser_stop",
            arguments={"session_id": ids["session_id"]},
        )
        assert repeated["session"]["cleanup"] == "COMPLETE"
        ended = await client.call_tool(name="browser_snapshot", arguments=ids)
        assert (
            ended.is_error and ended.structured_content["code"] == "SESSION_NOT_ACTIVE"
        )
    runtime.wait_free()
    runtime.check_exited(pids=pids)
    evidence(
        name=f"mcp_form_{mode}",
        facts={
            "protocol_version": negotiated,
            "tools": 26,
            "external_form_submissions": 1,
            "png_dimensions": [1280, 720],
            "cleanup": "COMPLETE",
            "resource": "FREE",
            "owned_browser_pids_exited": len(pids),
            "temporary_directory_removed": True,
        },
    )


@pytest.mark.parametrize("mode", ["auto", "legacy"])
@pytest.mark.asyncio
async def test_mcp_request_replay_upload_boundary_and_cleanup(runtime, website, mode):
    """官方 MCP 客户端核对同请求、实际 File 内容与最终资源释放。"""
    async with agent(runtime=runtime, mode=mode) as client:
        start = {"node_id": runtime.identity["node_id"], "request_id": f"upload_{mode}"}
        started = await invoke(client=client, name="browser_start", arguments=start)
        ids = {
            "session_id": started["session"]["session_id"],
            "page_id": started["page_id"],
        }
        pids = runtime.browser_pids()
        assert os.name != "posix" or pids
        try:
            repeated = await invoke(
                client=client, name="browser_start", arguments=start
            )
            assert (
                repeated["session"]["session_id"] == ids["session_id"]
                and repeated["page_id"] == ids["page_id"]
            )
            status = await invoke(
                client=client, name="browser_sessions", arguments=start
            )
            assert (
                status["request"]["state"] == "SUCCEEDED"
                and status["request"]["session_id"] == ids["session_id"]
            )
            await invoke(
                client=client,
                name="browser_navigate",
                arguments={**ids, "url": website["url"]},
            )
            target = {"by": "css", "value": "#files"}
            for sizes in [[4 * 1024 * 1024], [2 * 1024 * 1024, 2 * 1024 * 1024]]:
                files, expected = [], []
                for index, size in enumerate(sizes):
                    raw = bytes(range(256)) * (size // 256)
                    name = f"fixture{index}.bin"
                    files.append(
                        {
                            "name": name,
                            "mime_type": "application/octet-stream",
                            "data": base64.b64encode(raw).decode(),
                        }
                    )
                    expected.append(
                        {
                            "name": name,
                            "size": size,
                            "sha256": hashlib.sha256(raw).hexdigest(),
                        }
                    )
                await invoke(
                    client=client,
                    name="browser_file_upload",
                    arguments={**ids, "target": target, "files": files},
                )
                text = f"FILES:{json.dumps(expected, separators=(',', ':'))}"
                await invoke(
                    client=client,
                    name="browser_wait_for",
                    arguments={
                        **ids,
                        "target": {"by": "css", "value": "#file_sizes"},
                        "state": "text",
                        "value": text,
                    },
                )
                captured = await invoke(
                    client=client,
                    name="browser_capture",
                    arguments={
                        **ids,
                        "allowed_origins": [website["url"]],
                        "captures": {
                            "files": {"mode": "text", "selector": "#file_sizes"}
                        },
                    },
                )
                assert (
                    json.loads(captured["values"]["files"].removeprefix("FILES:"))
                    == expected
                    and captured["truncated"] is False
                )
            oversized = base64.b64encode(b"x" * (4 * 1024 * 1024 + 1)).decode()
            failure = await client.call_tool(
                name="browser_file_upload",
                arguments={
                    **ids,
                    "target": target,
                    "files": [
                        {
                            "name": "oversized.bin",
                            "mime_type": "application/octet-stream",
                            "data": oversized,
                        }
                    ],
                },
            )
            assert (
                failure.is_error
                and failure.structured_content["code"] == "UPLOAD_TOO_LARGE"
            )
            current = await invoke(
                client=client,
                name="browser_read",
                arguments={**ids, "target": {"by": "css", "value": "#file_sizes"}},
            )
            assert json.loads(current["value"].removeprefix("FILES:")) == expected
            await invoke(
                client=client,
                name="browser_file_upload",
                arguments={**ids, "target": target, "files": []},
            )
            await invoke(
                client=client,
                name="browser_wait_for",
                arguments={
                    **ids,
                    "target": {"by": "css", "value": "#file_sizes"},
                    "state": "text",
                    "value": "FILES:[]",
                },
            )
        finally:
            stopped = await invoke(
                client=client,
                name="browser_stop",
                arguments={"session_id": ids["session_id"]},
            )
        assert (
            stopped["session"]["state"] == "CLOSED"
            and stopped["session"]["cleanup"] == "COMPLETE"
        )
        recovered = await invoke(
            client=client, name="browser_sessions", arguments=start
        )
        assert (
            recovered["request"]["state"] == "SUCCEEDED"
            and recovered["sessions"][0]["session"]["cleanup"] == "COMPLETE"
        )
        closed = await invoke(client=client, name="browser_start", arguments=start)
        assert (
            closed["session"]["state"] == "CLOSED"
            and closed["session"]["session_id"] == ids["session_id"]
        )
    runtime.wait_free()
    runtime.check_exited(pids=pids)
    evidence(
        name=f"mcp_request_and_upload_{mode}",
        facts={
            "request_replay_same_session": True,
            "single_file_bytes": 4194304,
            "multiple_file_total_bytes": 4194304,
            "browser_file_sha256_verified": True,
            "over_limit_preserves_previous_files": True,
            "cleared_files": True,
            "closed_request_not_recreated": True,
            "cleanup": "COMPLETE",
            "resource": "FREE",
            "owned_browser_pids_exited": len(pids),
            "temporary_directories_removed": True,
        },
    )


@pytest.mark.asyncio
async def test_mcp_grant_isolation_revocation_and_inflight_interrupt(runtime, website):
    access = runtime.grant()
    other = runtime.grant()
    restricted = runtime.grant(resources=["other_resource"])
    async with (
        agent(runtime=runtime, access=access) as first,
        agent(runtime=runtime, access=other) as second,
        agent(runtime=runtime, access=restricted) as limited,
    ):
        denied = await limited.call_tool(
            name="browser_start",
            arguments={
                "node_id": runtime.identity["node_id"],
                "resource_id": "chromium",
            },
        )
        assert (
            denied.is_error
            and denied.structured_content["code"] == "RESOURCE_OUTSIDE_GRANT"
        )
        started = await invoke(
            client=first,
            name="browser_start",
            arguments={"node_id": runtime.identity["node_id"]},
        )
        ids = {
            "session_id": started["session"]["session_id"],
            "page_id": started["page_id"],
        }
        pids = runtime.browser_pids()
        for name in ["browser_status", "browser_stop", "browser_snapshot"]:
            rejected = await second.call_tool(
                name=name,
                arguments=ids
                if name == "browser_snapshot"
                else {"session_id": ids["session_id"]},
            )
            assert (
                rejected.is_error
                and rejected.structured_content["code"] == "SESSION_OUTSIDE_GRANT"
            )
        assert (
            await invoke(
                client=second,
                name="browser_sessions",
                arguments={"node_id": runtime.identity["node_id"]},
            )
        )["sessions"] == []
        await invoke(
            client=first,
            name="browser_navigate",
            arguments={**ids, "url": website["url"]},
        )
        waiting = asyncio.create_task(
            first.call_tool(
                name="browser_wait_for",
                arguments={
                    **ids,
                    "target": {"by": "text", "value": "不会出现"},
                    "timeout_ms": 30000,
                },
            )
        )
        await asyncio.sleep(0.2)
        before = time.monotonic()
        response = await asyncio.to_thread(
            runtime.http.delete,
            url=f"{runtime.url}/v1/nodes/{runtime.identity['node_id']}/grants/{access['grant_id']}",
            headers={"Authorization": f"Bearer {runtime.identity['node_token']}"},
        )
        assert response.status_code == 204
        interrupted = await asyncio.wait_for(waiting, timeout=5)
        assert (
            interrupted.is_error
            and interrupted.structured_content["code"] == "OPERATION_INTERRUPTED"
        )
        assert time.monotonic() - before < 5
        assert (
            runtime.http.post(
                url=f"{runtime.url}/mcp",
                headers={"Authorization": f"Bearer {access['access_token']}"},
            ).status_code
            == 401
        )
    runtime.wait_free()
    runtime.check_exited(pids=pids)
    evidence(
        name="mcp_permissions_and_revoke",
        facts={
            "other_grant_denied": True,
            "resource_scope_checked": True,
            "pending_operation_interrupted": True,
            "revoked_http_status": 401,
            "resource": "FREE",
        },
    )


@pytest.mark.asyncio
async def test_mcp_transport_disconnect_keeps_lease_then_expires(runtime):
    async with agent(runtime=runtime) as client:
        started = await invoke(
            client=client,
            name="browser_start",
            arguments={"node_id": runtime.identity["node_id"], "lease_seconds": 3},
        )
        session_id = started["session"]["session_id"]
        pids = runtime.browser_pids()
    assert runtime.query(session_id=session_id).json()["state"] == "ACTIVE"
    async with agent(runtime=runtime) as client:
        listing = await invoke(
            client=client,
            name="browser_sessions",
            arguments={"node_id": runtime.identity["node_id"]},
        )
        assert listing["sessions"][0]["session"]["session_id"] == session_id
    runtime.wait_free()
    closed = runtime.query(session_id=session_id).json()
    assert (
        closed["close_reason"] == "SESSION_EXPIRED" and closed["cleanup"] == "COMPLETE"
    )
    runtime.check_exited(pids=pids)
    evidence(
        name="mcp_disconnect_and_lease",
        facts={
            "transport_disconnect_retains_session": True,
            "new_client_can_recover": True,
            "close_reason": "SESSION_EXPIRED",
            "cleanup": "COMPLETE",
            "resource": "FREE",
        },
    )


@pytest.mark.asyncio
async def test_mcp_stop_during_wait_and_grant_expiry_limit(runtime):
    async with agent(runtime=runtime) as client:
        started = await invoke(
            client=client,
            name="browser_start",
            arguments={"node_id": runtime.identity["node_id"]},
        )
        ids = {
            "session_id": started["session"]["session_id"],
            "page_id": started["page_id"],
        }
        waiting = asyncio.create_task(
            client.call_tool(
                name="browser_wait_for",
                arguments={
                    **ids,
                    "target": {"by": "text", "value": "不会出现"},
                    "timeout_ms": 30000,
                },
            )
        )
        await asyncio.sleep(0.2)
        stopped = await asyncio.wait_for(
            invoke(
                client=client,
                name="browser_stop",
                arguments={"session_id": ids["session_id"]},
            ),
            timeout=5,
        )
        interrupted = await asyncio.wait_for(waiting, timeout=1)
        assert (
            interrupted.is_error
            and interrupted.structured_content["code"] == "OPERATION_INTERRUPTED"
        )
        assert (
            stopped["session"]["state"] == "CLOSED"
            and stopped["session"]["cleanup"] == "COMPLETE"
        )
    runtime.wait_free()
    access = runtime.grant(expires=3)
    async with agent(runtime=runtime, access=access) as client:
        started = await invoke(
            client=client,
            name="browser_start",
            arguments={"node_id": runtime.identity["node_id"], "lease_seconds": 300},
        )
        assert datetime.fromisoformat(
            started["session"]["expires_at"]
        ) == datetime.fromisoformat(access["expires_at"])
    runtime.wait_free()
    assert (
        runtime.query(
            session_id=started["session"]["session_id"], access=access
        ).status_code
        == 401
    )
    evidence(
        name="mcp_stop_and_grant_expiry",
        facts={
            "stop_interrupts_wait": True,
            "cleanup": "COMPLETE",
            "lease_capped_by_grant": True,
            "expired_token_status": 401,
            "resource": "FREE",
        },
    )


@pytest.mark.asyncio
async def test_documented_mcp_client_example(runtime, website):
    access_file = runtime.directory / "example-access.json"
    access_file.write_text(json.dumps({**runtime.access, "hub_url": runtime.url}))
    access_file.chmod(0o600)
    screenshot = runtime.directory / "example.png"
    completed = await asyncio.to_thread(
        subprocess.run,
        [
            runtime.executable(project=HUB, name="python"),
            str(
                Path(__file__).resolve().parents[1]
                / "doc/reference/examples/mcp_browser.py"
            ),
            "--access-file",
            str(access_file),
            "--url",
            website["url"],
            "--screenshot",
            str(screenshot),
        ],
        cwd=HUB,
        env=runtime.environment,
        capture_output=True,
        text=True,
        timeout=45,
    )
    assert completed.returncode == 0, "文档中的实际 MCP 客户端示例运行失败"
    assert not any(
        secret in completed.stdout + completed.stderr for secret in runtime.credentials
    ), "示例输出泄露了凭据"
    result = json.loads(completed.stdout)
    assert result["state"] == "CLOSED" and result["cleanup"] == "COMPLETE"
    assert result["snapshot_characters"] > 0 and screenshot.read_bytes().startswith(
        b"\x89PNG\r\n\x1a\n"
    )
    runtime.wait_free()
    evidence(
        name="mcp_documented_example",
        facts={
            "example_exit_code": 0,
            "snapshot_read": True,
            "png_saved": True,
            "cleanup": "COMPLETE",
            "resource": "FREE",
        },
    )


@pytest.fixture
def rich_site():
    """覆盖已公开工具的页面效果，所有脚本只属于测试夹具。"""

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            html = """<!doctype html><meta charset="utf-8"><title>扩展动作</title>
<style>body{margin:0;background:rgb(30,60,90)}#source,#dest{width:80px;height:40px;background:white;margin:10px}</style>
<select id="select"><option value="a">甲</option><option value="b">乙</option></select>
<input type="checkbox" id="check"><input id="key" onkeydown="document.querySelector('#key_result').textContent=event.key"><span id="key_result"></span>
<button id="hover" onmouseover="document.querySelector('#hover_result').textContent='hovered'">悬停</button><span id="hover_result"></span>
<div id="source" draggable="true" ondragstart="event.dataTransfer.setData('text/plain','moved')">拖动</div>
<div id="dest" ondragover="event.preventDefault()" ondrop="event.preventDefault();document.querySelector('#drag_result').textContent=event.dataTransfer.getData('text/plain')">放置</div><span id="drag_result"></span>
<button id="dialog" onclick="document.querySelector('#dialog_result').textContent=prompt('输入值')">弹窗</button><span id="dialog_result"></span>
<iframe name="child" id="frame" srcdoc="<label>框内<input id='inner'></label>"></iframe>
<a href="/second">下一页</a><div style="height:2000px"></div>""".encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(html)))
            self.end_headers()
            self.wfile.write(html)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


@pytest.mark.asyncio
async def test_all_remaining_tools_and_visual_same_page(runtime, rich_site):
    """逐项调用剩余动作并读取页面效果，画面绑定同一公开 page_id。"""
    from websockets.asyncio.client import connect
    from runbridge_hub.visual_wire import unpack_frame

    async with agent(runtime=runtime) as client:
        started = await invoke(
            client=client,
            name="browser_start",
            arguments={"node_id": runtime.identity["node_id"]},
        )
        sid = started["session"]["session_id"]
        ids = {"session_id": sid, "page_id": started["page_id"]}

        def css(selector):
            return {"by": "css", "value": selector}

        async def action(name, **params):
            return await invoke(client=client, name=name, arguments={**ids, **params})

        async def read(selector):
            return (await action("browser_read", target=css(selector)))["value"]

        try:
            await action("browser_navigate", url=rich_site)
            assert (await action("browser_inspect_dom", selector="select,input"))[
                "elements"
            ]
            assert (
                await action(
                    "browser_select_option", target=css("#select"), values=["b"]
                )
            )["selected"] == ["b"]
            assert (await action("browser_check", target=css("#check"), checked=True))[
                "checked"
            ] is True
            await action("browser_hover", target=css("#hover"))
            assert await read("#hover_result") == "hovered"
            await action("browser_press_key", target=css("#key"), key="K")
            assert await read("#key_result") == "K"
            await action("browser_press_key", key="Escape")
            await action("browser_drag", source=css("#source"), target=css("#dest"))
            assert await read("#drag_result") == "moved"
            frames = await action("browser_frames")
            assert any(frame["name"] == "child" for frame in frames["frames"])
            target = {"by": "label", "value": "框内", "frame_selector": "#frame"}
            await action("browser_fill", target=target, value="iframe value")
            assert (await action("browser_read", target=target, kind="input_value"))[
                "value"
            ] == "iframe value"
            await action("browser_handle_dialog", accept=True, prompt_text="confirmed")
            await action("browser_click", target=css("#dialog"))
            assert await read("#dialog_result") == "confirmed"
            await action("browser_click", target=css("#dialog"))
            assert await read("#dialog_result") == ""
            resize = await action("browser_resize", width=900, height=600)
            assert resize["width"] == 900 and resize["height"] == 600
            await action("browser_scroll", delta_y=500)
            await action("browser_navigate", url=rich_site + "/second")
            assert (await action("browser_navigate_back"))["url"] == rich_site + "/"
            captured = await action(
                "browser_capture",
                allowed_origins=[rich_site],
                captures={"inputs": {"mode": "count", "selector": "input"}},
            )
            assert captured["values"]["inputs"] == 2
            outside = await client.call_tool(
                name="browser_capture",
                arguments={
                    **ids,
                    "allowed_origins": ["https://other.test"],
                    "captures": {"url": {"mode": "url"}},
                },
            )
            assert (
                outside.is_error
                and outside.structured_content["code"] == "CAPTURE_OUTSIDE_ORIGIN"
            )
            queried = await invoke(
                client=client,
                name="tool_request_status",
                arguments={"session_id": sid, "request_id": captured["request_id"]},
            )
            assert queried["status"] == "SUCCEEDED"
            tabs = await invoke(
                client=client,
                name="browser_tabs",
                arguments={"session_id": sid, "action": "new"},
            )
            new_page = tabs["page_id"]
            await action(
                "browser_navigate", page_id=new_page, url=rich_site + "/second"
            )
            selected = await invoke(
                client=client,
                name="browser_tabs",
                arguments={
                    "session_id": sid,
                    "action": "select",
                    "page_id": ids["page_id"],
                },
            )
            assert selected["default_page_id"] == ids["page_id"]
            listing = await invoke(
                client=client,
                name="browser_tabs",
                arguments={"session_id": sid, "action": "list"},
            )
            assert len(listing["pages"]) == 2
            visual_path = (
                await invoke(
                    client=client, name="browser_status", arguments={"session_id": sid}
                )
            )["visual"]["stream_path"]
            async with connect(
                uri=runtime.url.replace("http", "ws", 1) + visual_path,
                additional_headers={
                    "Authorization": "Bearer " + runtime.access["access_token"]
                },
            ) as stream:
                async with asyncio.timeout(10):
                    while True:
                        packet = await stream.recv()
                        if isinstance(packet, str):
                            (runtime.directory / "visual-latest-state.json").write_text(
                                packet
                            )
                        if isinstance(packet, bytes):
                            metadata, png = unpack_frame(data=packet)
                            if metadata.target_id == ids["page_id"]:
                                assert png.startswith(
                                    b"\x89PNG\r\n\x1a\n"
                                ) and struct.unpack(">II", png[16:24]) == (900, 600)
                                break
                response = await asyncio.to_thread(
                    runtime.http.put,
                    url=f"{runtime.url}/v1/sessions/{sid}/visual/target",
                    headers={
                        "Authorization": "Bearer " + runtime.access["access_token"]
                    },
                    json={"target_id": new_page},
                )
                assert response.status_code == 202, response.text
                async with asyncio.timeout(10):
                    while True:
                        packet = await stream.recv()
                        if (
                            isinstance(packet, bytes)
                            and unpack_frame(data=packet)[0].target_id == new_page
                        ):
                            break
                await invoke(
                    client=client,
                    name="browser_tabs",
                    arguments={
                        "session_id": sid,
                        "action": "select",
                        "page_id": ids["page_id"],
                    },
                )
                async with asyncio.timeout(10):
                    while True:
                        packet = await stream.recv()
                        if isinstance(packet, bytes):
                            metadata, png = unpack_frame(data=packet)
                            if metadata.target_id == ids["page_id"]:
                                break
                first_frame = metadata.frame_id
                await action("browser_fill", target=css("#key"), value="screen changed")
                async with asyncio.timeout(10):
                    while True:
                        packet = await stream.recv()
                        if isinstance(packet, str):
                            (runtime.directory / "visual-latest-state.json").write_text(
                                packet
                            )
                        if isinstance(packet, bytes):
                            later, changed = unpack_frame(data=packet)
                            if (
                                later.target_id == ids["page_id"]
                                and later.frame_id > first_frame
                                and changed != png
                            ):
                                break
            await invoke(
                client=client,
                name="browser_tabs",
                arguments={"session_id": sid, "action": "close", "page_id": new_page},
            )
            assert (
                len(
                    (
                        await invoke(
                            client=client,
                            name="browser_status",
                            arguments={"session_id": sid},
                        )
                    )["pages"]
                )
                == 1
            )
        finally:
            stopped = await invoke(
                client=client, name="browser_stop", arguments={"session_id": sid}
            )
            assert stopped["session"]["cleanup"] == "COMPLETE"
    runtime.wait_free()
    evidence(
        name="all_tools_and_managed_visual",
        facts={
            "original_tools": 26,
            "new_tool_request_status": True,
            "frame_target_matches_page": True,
            "frame_dimensions": [900, 600],
            "frame_changes_after_fill": True,
            "iframe_value_verified": True,
            "dialog_once_then_dismiss": True,
            "drag_drop_verified": True,
            "cleanup": "COMPLETE",
        },
    )


@pytest.mark.asyncio
async def test_http_context_page_references_and_closed_objects(runtime, website):
    """HTTP 独有的 Browser/Context/Page 方法与过期引用。"""
    access = runtime.access
    headers = {"Authorization": "Bearer " + access["access_token"]}
    response = runtime.http.post(
        url=f"{runtime.url}/v2/nodes/{access['node_id']}/sessions",
        headers=headers,
        json={"resource_id": "chromium", "request_id": "raw_refs"},
    )
    assert response.status_code == 201
    view = response.json()
    sid = view["session_id"]
    root = view["objects"]["root"]

    async def command(method, target, params=None, status="SUCCEEDED"):
        from uuid import uuid4

        response = await asyncio.to_thread(
            runtime.http.post,
            url=f"{runtime.url}/v2/sessions/{sid}/commands",
            headers=headers,
            json={
                "request_id": "raw_" + uuid4().hex,
                "method": method,
                "target": target,
                "params": params or {},
            },
        )
        assert response.status_code == 200, response.text
        value = response.json()
        assert value["status"] == status, value
        return value["result"]["value"] if status == "SUCCEEDED" else value

    try:
        assert len(await command("browser.contexts", root)) == 1
        context = await command(
            "browser.new_context",
            root,
            {"viewport": {"width": 800, "height": 500}, "locale": "en-US"},
        )
        assert await command("context.pages", context) == []
        page = await command("context.new_page", context)
        assert len(await command("context.pages", context)) == 1
        await command("page.goto", page, {"url": website["url"]})
        assert (
            await command(
                "locator.wait_for",
                {
                    **page,
                    "locator": [
                        {
                            "method": "get_by_label",
                            "params": {"text": "用户名", "exact": True},
                        }
                    ],
                },
                {"state": "visible"},
            )
        )["completed"]
        assert (
            await command(
                "locator.wait_for",
                {
                    **page,
                    "locator": [
                        {"method": "locator", "params": {"selector": "#absent"}}
                    ],
                },
                {"state": "hidden"},
            )
        )["completed"]
        assert await command("page.title", page) == "MCP 联调"
        assert await command("page.url", page) == website["url"] + "/"
        assert (await command("page.close", page))["completed"]
        assert (await command("page.title", page, status="FAILED"))["error"][
            "code"
        ] == "OBJECT_CLOSED"
        assert (await command("context.close", context))["completed"]
        assert (await command("context.pages", context, status="FAILED"))["error"][
            "code"
        ] == "OBJECT_CLOSED"
    finally:
        stopped = runtime.http.delete(
            url=f"{runtime.url}/v2/sessions/{sid}", headers=headers
        )
        assert stopped.json()["cleanup"] == "COMPLETE"
    runtime.wait_free()
    evidence(
        name="HTTP_reference_methods",
        facts={
            "browser_context_page_methods": True,
            "closed_reference_rejected": True,
            "cleanup": "COMPLETE",
        },
    )
