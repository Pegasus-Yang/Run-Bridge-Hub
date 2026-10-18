"""真实 HTTP 与执行 WebSocket 的去重、超时和未知结果。"""

import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient

from runbridge_hub.app import create_app
from test_r1 import auth, grant, register, settings
from test_sessions import live_session


def body(*, request_id="request_a", method="page.url", params=None):
    return {
        "request_id": request_id,
        "method": method,
        "target": {"type": "page", "id": "page_a"},
        "params": params or {},
    }


def success(*, execution, value="https://example.test/"):
    message = execution.receive_json()
    execution.send_json(
        {
            "protocol_version": 2,
            "type": "result",
            "request_id": message["request_id"],
            "session_id": message["session_id"],
            "connection_generation": message["connection_generation"],
            "status": "SUCCEEDED",
            "execution_outcome": "COMPLETED",
            "result": {"kind": "json", "value": value},
        }
    )
    return message


def test_commands_deduplicate_conflict_and_keep_result_private(tmp_path):
    with (
        TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        register(client=client)
        access, other = grant(client=client), grant(client=client)
        with live_session(client=client, access=access) as (view, _, execution, _):
            sid = view["session_id"]
            path = f"/v2/sessions/{sid}/commands"
            headers = auth(token=access["access_token"])
            running = pool.submit(client.post, url=path, headers=headers, json=body())
            message = success(execution=execution)
            first = running.result(timeout=3)
            assert first.json()["result"]["value"] == "https://example.test/"
            assert (
                message["tool"] == "playwright"
                and message["params"]["timeout"] == 10000
            )
            assert (
                client.post(url=path, headers=headers, json=body()).json()
                == first.json()
            )
            assert (
                client.post(
                    url=path, headers=headers, json=body(method="page.title")
                ).json()["code"]
                == "REQUEST_ID_CONFLICT"
            )
            assert (
                client.get(
                    url=path + "/request_a", headers=auth(token=other["access_token"])
                ).status_code
                == 403
            )
            assert (
                client.get(url=path + "/request_a", headers=headers).json()
                == first.json()
            )
            client.app.state.commands.cache.clear()
            expired = client.get(url=path + "/request_a", headers=headers).json()
            assert (
                expired["status"] == "SUCCEEDED"
                and expired["error"]["code"] == "RESULT_EXPIRED"
            )
            assert (
                client.post(url=path, headers=headers, json=body()).json()[
                    "result_available"
                ]
                is False
            )


def test_queue_timeout_never_dispatches_second_action(tmp_path):
    with (
        TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client,
        ThreadPoolExecutor(max_workers=2) as pool,
    ):
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, _, execution, _):
            path = f"/v2/sessions/{view['session_id']}/commands"
            headers = auth(token=access["access_token"])
            first = pool.submit(
                client.post,
                url=path,
                headers=headers,
                json=body(request_id="first", params={"timeout": 1000}),
            )
            message = execution.receive_json()
            second = pool.submit(
                client.post,
                url=path,
                headers=headers,
                json=body(request_id="second", params={"timeout": 20}),
            )
            time.sleep(0.1)
            execution.send_json(
                {
                    "protocol_version": 2,
                    "type": "result",
                    "request_id": "first",
                    "session_id": view["session_id"],
                    "connection_generation": message["connection_generation"],
                    "status": "SUCCEEDED",
                    "execution_outcome": "COMPLETED",
                    "result": {"kind": "json", "value": "done"},
                }
            )
            assert first.result(timeout=3).json()["status"] == "SUCCEEDED"
            result = second.result(timeout=3).json()
            assert (
                result["execution_outcome"] == "NOT_STARTED"
                and result["error"]["code"] == "ACTION_TIMEOUT"
            )


@pytest.mark.parametrize(
    "change",
    [
        {"method": "page.evaluate"},
        {"params": {"timeout": 0}},
        {"params": {"misspelled": True}},
        {"target": {"type": "context", "id": "context_a"}},
        {
            "target": {
                "type": "page",
                "id": "page_a",
                "locator": [{"method": "locator", "params": {"xpath": "//input"}}],
            }
        },
    ],
)
def test_invalid_command_fails_before_node_dispatch(tmp_path, change):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, *_):
            response = client.post(
                url=f"/v2/sessions/{view['session_id']}/commands",
                headers=auth(token=access["access_token"]),
                json={**body(), **change},
            )
            assert response.status_code == 422
            assert not client.app.state.commands.pending


def test_execution_disconnect_never_replays_pending_command(tmp_path):
    with (
        TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client,
        ThreadPoolExecutor(max_workers=1) as pool,
    ):
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (
            view,
            control,
            execution,
            generation,
        ):
            path = f"/v2/sessions/{view['session_id']}/commands"
            headers = auth(token=access["access_token"])
            running = pool.submit(client.post, url=path, headers=headers, json=body())
            execution.receive_json()
            execution.close()
            result = running.result(timeout=3).json()
            assert (
                result["status"] == "UNKNOWN"
                and result["execution_outcome"] == "OUTCOME_UNKNOWN"
            )
            assert client.post(url=path, headers=headers, json=body()).json() == result


@pytest.mark.parametrize("chunked", [False, True])
def test_http_body_limit_precedes_json_parse(tmp_path, chunked):
    from runbridge_hub.tool_contract import MAX_MESSAGE

    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        payload = b"x" * (MAX_MESSAGE + 1)
        content = iter([payload[:100], payload[100:]]) if chunked else payload
        response = client.post(
            url="/v2/nodes/node_a/sessions",
            content=content,
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413
        assert response.json()["code"] == "REQUEST_TOO_LARGE"


def test_caller_cancellation_during_admission_does_not_strand_command(
    tmp_path, monkeypatch
):
    import asyncio
    import threading
    from runbridge_hub.tool_contract import CommandInput

    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with live_session(client=client, access=access) as (view, _, execution, _):
            entered = threading.Event()
            resume = asyncio.Event()
            service = client.app.state.commands
            original = service.store.begin_command

            async def pause(**kwargs):
                value = await original(**kwargs)
                entered.set()
                await resume.wait()
                return value

            monkeypatch.setattr(service.store, "begin_command", pause)

            async def submit():
                return await service.submit(
                    session_id=view["session_id"],
                    token=access["access_token"],
                    request=CommandInput.model_validate(body()),
                )

            caller = client.portal.start_task_soon(submit)
            assert entered.wait(timeout=2)
            caller.cancel()
            client.portal.call(resume.set)
            success(execution=execution)
            deadline = time.monotonic() + 2
            while time.monotonic() < deadline:
                result = client.get(
                    url=f"/v2/sessions/{view['session_id']}/commands/request_a",
                    headers=auth(token=access["access_token"]),
                ).json()
                if result["status"] == "SUCCEEDED":
                    break
                time.sleep(0.01)
            assert result["status"] == "SUCCEEDED"
