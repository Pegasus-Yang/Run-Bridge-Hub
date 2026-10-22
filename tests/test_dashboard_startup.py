"""启动日志中的只读口令、可点击链接与实际监听端口。"""

import asyncio
import logging
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import uvicorn
from pydantic import SecretStr

from runbridge_hub.app import create_app
from runbridge_hub.dashboard import log_access
from runbridge_hub.server import HubServer
from runbridge_hub.settings import HubSettings


@pytest.mark.parametrize("host", ["127.0.0.1", "0.0.0.0"])
@pytest.mark.parametrize("configured", [True, False])
async def test_startup_logs_valid_token_and_actual_url(tmp_path, caplog, host, configured):
    """配置口令和自动口令均可直接访问，特殊字符不破坏 URL。"""
    enrollment = "e" * 64
    value = "readonly-+&=/%?#" * 4 if configured else None
    settings = HubSettings(
        database_path=tmp_path / "hub.sqlite3", enrollment_token=enrollment,
        web_token=value,
    )
    caplog.set_level(level=logging.INFO, logger="uvicorn.error")
    server = HubServer(config=uvicorn.Config(
        app=create_app(settings=settings), host=host, port=0, log_config=None,
    ))
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        token = value if configured else (tmp_path / "web.token").read_text().strip()
        assert f"Dashboard 只读口令：{token}" in caplog.messages
        urls = [message.removeprefix("Dashboard URL：") for message in caplog.messages if message.startswith("Dashboard URL：")]
        assert len(urls) == 1
        url = urlsplit(url=urls[0])
        assert url.hostname == "127.0.0.1"
        assert url.port == server.servers[0].sockets[0].getsockname()[1]
        assert url.port != 0
        assert url.path == "/dashboard"
        assert parse_qs(qs=url.query) == {"token": [token]}
        assert enrollment not in caplog.text
        async with httpx.AsyncClient(trust_env=False) as client:
            assert (await client.get(url=urls[0])).status_code == 200
            api = f"http://127.0.0.1:{url.port}/dashboard/api/nodes"
            assert (await client.get(url=api, headers={"Authorization": f"Bearer {token}"})).status_code == 200
            assert (await client.get(url=f"{api}?{url.query}")).status_code == 401
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)


async def test_disabled_web_does_not_log_or_generate_token(tmp_path, caplog):
    """关闭总览时不输出口令或入口。"""
    caplog.set_level(level=logging.INFO, logger="uvicorn.error")
    settings = HubSettings(
        database_path=tmp_path / "hub.sqlite3", enrollment_token="e" * 64,
        web_enabled=False,
    )
    server = HubServer(config=uvicorn.Config(
        app=create_app(settings=settings), host="127.0.0.1", port=0, log_config=None,
    ))
    task = asyncio.create_task(server.serve())
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        assert not any(message.startswith("Dashboard ") for message in caplog.messages)
        assert not (tmp_path / "web.token").exists()
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)


@pytest.mark.parametrize("host,authority", [("::", "[::1]"), ("::1", "[::1]"), ("2001:db8::5", "[2001:db8::5]")])
def test_ipv6_dashboard_url_is_clickable(caplog, host, authority):
    """IPv6 链接使用方括号和真实端口。"""
    caplog.set_level(level=logging.INFO, logger="uvicorn.error")
    token = "readonly-" + "w" * 48
    log_access(token=SecretStr(secret_value=token), host=host, port=9000)
    assert f"Dashboard URL：http://{authority}:9000/dashboard?token={token}" in caplog.messages
