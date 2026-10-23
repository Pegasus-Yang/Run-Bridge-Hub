"""会话独占、对象目录、权限与执行通道的合同测试。"""

import sqlite3
import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient

from runbridge_hub.app import create_app
from runbridge_hub.tool_contract import METHODS
from test_r1 import IDENTITY, auth, grant, register, settings


def publish(*, websocket, readiness="READY", occupancy="FREE", methods=None):
    generation = websocket.receive_json()["connection_generation"]
    websocket.send_json(
        {
            "type": "capabilities",
            "connection_generation": generation,
            "capabilities": {
                "backends": [
                    {
                        "name": "playwright",
                        "runtime_version": "1.63.0",
                        "coverage_status": "SUPPORTED",
                    }
                ],
                "resources": [
                    {
                        "resource_id": "chromium",
                        "backend": "playwright",
                        "kind": "MANAGED_CHROMIUM",
                        "readiness": readiness,
                        "occupancy": occupancy,
                        "methods": list(METHODS) if methods is None else methods,
                    }
                ],
            },
        }
    )
    assert websocket.receive_json()["type"] == "capabilities_ack"
    return generation


def report(*, control, generation, session_id, type, **values):
    control.send_json(
        {
            "type": type,
            "connection_generation": generation,
            "session_id": session_id,
            **values,
        }
    )
    assert control.receive_json()["type"] == "session_ack"


def objects():
    return {
        "root": {"type": "browser", "id": "browser_a"},
        "contexts": [{"type": "context", "id": "context_a"}],
        "pages": [
            {
                "type": "page",
                "id": "page_a",
                "page_id": "page_a",
                "context_id": "context_a",
                "url": "about:blank",
            }
        ],
        "default_page_id": "page_a",
        "ownership": "managed",
        "last_dialog": {},
    }


@contextmanager
def live_session(*, client, access, cleanup="COMPLETE"):
    with (
        ThreadPoolExecutor(max_workers=1) as pool,
        client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as control,
    ):
        generation = publish(websocket=control)
        opening = pool.submit(
            client.post,
            url="/v2/nodes/node_a/sessions",
            headers=auth(token=access["access_token"]),
            json={"resource_id": "chromium", "request_id": "open_a"},
        )
        opened = control.receive_json()
        sid = opened["session_id"]
        headers = {**auth(token=IDENTITY), "x-runbridge-generation": str(generation)}
        with client.websocket_connect(
            url=f"/v2/nodes/node_a/sessions/{sid}/execution", headers=headers
        ) as execution:
            report(
                control=control,
                generation=generation,
                session_id=sid,
                type="session_prepared",
                runtime_version="1.63.0",
                objects=objects(),
            )
            response = opening.result(timeout=3)
            assert response.status_code == 201, response.text
            try:
                yield response.json(), control, execution, generation
            finally:
                current = client.app.state.sessions.sessions.get(sid)
                if current and current.view.state not in {
                    "CLOSED",
                    "FAILED",
                    "INTERRUPTED",
                }:
                    releasing = pool.submit(
                        client.delete,
                        url=f"/v2/sessions/{sid}",
                        headers=auth(token=access["access_token"]),
                    )
                    assert control.receive_json()["type"] == "session_stop"
                    report(
                        control=control,
                        generation=generation,
                        session_id=sid,
                        type="session_closed",
                        cleanup=cleanup,
                    )
                    releasing.result(timeout=3)


@pytest.mark.parametrize(
    "readiness,occupancy,methods,code",
    [
        ("UNAVAILABLE", "FREE", None, "RESOURCE_NOT_READY"),
        ("READY", "BUSY", None, "RESOURCE_BUSY"),
        ("READY", "FREE", [], "TOOL_API_UNSUPPORTED"),
    ],
)
def test_resource_must_be_ready_free_and_compatible(
    tmp_path, readiness, occupancy, methods, code
):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as control:
            publish(
                websocket=control,
                readiness=readiness,
                occupancy=occupancy,
                methods=methods,
            )
            response = client.post(
                url="/v2/nodes/node_a/sessions",
                headers=auth(token=access["access_token"]),
                json={"resource_id": "chromium"},
            )
            assert response.json()["code"] == code


def test_scope_idempotent_open_and_same_id_conflict(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access, other = grant(client=client), grant(client=client)
        with live_session(client=client, access=access) as (view, *_):
            repeated = client.post(
                url="/v2/nodes/node_a/sessions",
                headers=auth(token=access["access_token"]),
                json={"resource_id": "chromium", "request_id": "open_a"},
            )
            assert repeated.json()["session_id"] == view["session_id"]
            conflict = client.post(
                url="/v2/nodes/node_a/sessions",
                headers=auth(token=access["access_token"]),
                json={
                    "resource_id": "chromium",
                    "request_id": "open_a",
                    "lease_seconds": 60,
                },
            )
            assert conflict.json()["code"] == "REQUEST_ID_CONFLICT"
            assert (
                client.get(
                    url=f"/v2/sessions/{view['session_id']}",
                    headers=auth(token=other["access_token"]),
                ).status_code
                == 403
            )
            assert "native_path" not in view and view["protocol_version"] == 2


def test_old_native_paths_return_explicit_retirement(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        assert client.post(url="/v1/nodes/node_a/sessions", json={}).status_code == 410
        assert (
            client.get(url="/v1/sessions/session_a/playwright").json()["code"]
            == "NATIVE_API_RETIRED"
        )


def test_schema_one_migrates_without_losing_identity(tmp_path):
    configuration = settings(tmp_path=tmp_path)
    with sqlite3.connect(database=configuration.database_path) as database:
        database.executescript(
            "CREATE TABLE nodes (node_id TEXT PRIMARY KEY, name TEXT NOT NULL, token_hash TEXT NOT NULL, generation INTEGER NOT NULL DEFAULT 0, capabilities TEXT, capabilities_observed_at TEXT, last_seen_at TEXT); CREATE TABLE grants (grant_id TEXT PRIMARY KEY, node_id TEXT NOT NULL REFERENCES nodes(node_id), token_hash TEXT NOT NULL UNIQUE, resource_ids TEXT, created_at TEXT NOT NULL, expires_at TEXT, revoked_at TEXT); PRAGMA user_version=1;"
        )
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        assert register(client=client)["created"] is False
    with sqlite3.connect(database=configuration.database_path) as database:
        assert database.execute("PRAGMA user_version").fetchone()[0] == 5
        assert database.execute("SELECT COUNT(*) FROM nodes").fetchone()[0] == 1
        assert database.execute("SELECT COUNT(*) FROM commands").fetchone()[0] == 0


def test_caller_cancellation_keeps_allocated_session_findable(tmp_path):
    from runbridge_hub.protocol import SessionCreate

    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with client.websocket_connect(
            url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)
        ) as control:
            generation = publish(websocket=control)

            async def opening():
                return await client.app.state.sessions.create(
                    node_id="node_a",
                    token=access["access_token"],
                    request=SessionCreate(
                        resource_id="chromium", request_id="cancel_open"
                    ),
                )

            caller = client.portal.start_task_soon(opening)
            opened = control.receive_json()
            sid = opened["session_id"]
            caller.cancel()
            with client.websocket_connect(
                url=f"/v2/nodes/node_a/sessions/{sid}/execution",
                headers={
                    **auth(token=IDENTITY),
                    "x-runbridge-generation": str(generation),
                },
            ):
                report(
                    control=control,
                    generation=generation,
                    session_id=sid,
                    type="session_prepared",
                    runtime_version="1.63.0",
                    objects=objects(),
                )
                response = client.post(
                    url="/v2/nodes/node_a/sessions",
                    headers=auth(token=access["access_token"]),
                    json={"resource_id": "chromium", "request_id": "cancel_open"},
                )
                assert (
                    response.status_code == 201 and response.json()["session_id"] == sid
                )
                with ThreadPoolExecutor(max_workers=1) as pool:
                    releasing = pool.submit(
                        client.delete,
                        url=f"/v2/sessions/{sid}",
                        headers=auth(token=access["access_token"]),
                    )
                    assert control.receive_json()["type"] == "session_stop"
                    report(
                        control=control,
                        generation=generation,
                        session_id=sid,
                        type="session_closed",
                        cleanup="COMPLETE",
                    )
                    assert releasing.result(timeout=3).json()["cleanup"] == "COMPLETE"


def test_historical_v1_session_keeps_original_version_and_metadata(tmp_path):
    import json

    configuration = settings(tmp_path=tmp_path)
    with TestClient(app=create_app(settings=configuration)) as client:
        register(client=client)
        access = grant(client=client)
        record = {
            "protocol_version": 1,
            "session_id": "session_old",
            "node_id": "node_a",
            "resource_id": "chromium",
            "grant_id": access["grant_id"],
            "connection_generation": 1,
            "backend": "playwright",
            "runtime_version": "1.63.0",
            "client_version": "1.63.0",
            "native_protocol": "playwright",
            "native_path": "/v1/sessions/session_old/playwright",
            "state": "ACTIVE",
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "expires_at": "2030-01-01T00:00:00Z",
        }

        async def save():
            await client.app.state.service.store.save_session(
                session_id="session_old",
                node_id="node_a",
                grant_id=access["grant_id"],
                record=json.dumps(record),
            )

        client.portal.call(save)
    with TestClient(app=create_app(settings=configuration)) as client:
        response = client.get(
            url="/v2/sessions/session_old", headers=auth(token=access["access_token"])
        )
        assert response.status_code == 401
        async def original():
            return await client.app.state.service.store.session(session_id="session_old")
        view = client.portal.call(original)
        assert (
            view["protocol_version"] == 1
            and view["state"] == "INTERRUPTED"
            and view["cleanup"] == "UNKNOWN"
        )
    with sqlite3.connect(configuration.database_path) as db:
        stored = json.loads(
            db.execute(
                "SELECT record FROM sessions WHERE session_id='session_old'"
            ).fetchone()[0]
        )
    assert stored["protocol_version"] == 1 and stored["client_version"] == "1.63.0"
    assert stored["native_protocol"] == "playwright" and stored["native_path"] is None


def test_prepared_response_waits_until_ready_is_persisted(tmp_path, monkeypatch):
    """首条指令紧随创建返回时不能读到 PREPARING。"""
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client, ThreadPoolExecutor(max_workers=2) as pool:
        register(client=client)
        access = grant(client=client)
        entered, resume = threading.Event(), asyncio.Event()
        service = client.app.state.sessions
        original = service.save

        async def delayed(*, view, request_id=None):
            if view.state == "READY":
                entered.set()
                await resume.wait()
            await original(view=view, request_id=request_id)

        monkeypatch.setattr(service, "save", delayed)
        with client.websocket_connect(url="/v2/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
            generation = publish(websocket=control)
            creating = pool.submit(client.post, url="/v2/nodes/node_a/sessions", headers=auth(token=access["access_token"]), json={"resource_id": "chromium"})
            sid = control.receive_json()["session_id"]
            with client.websocket_connect(url=f"/v2/nodes/node_a/sessions/{sid}/execution", headers={**auth(token=IDENTITY), "x-runbridge-generation": str(generation)}):
                control.send_json({"type": "session_prepared", "connection_generation": generation, "session_id": sid, "runtime_version": "1.63.0", "objects": objects()})
                assert entered.wait(timeout=2)
                try:
                    assert not creating.done()
                finally:
                    client.portal.call(resume.set)
                assert control.receive_json()["type"] == "session_ack"
                assert creating.result(timeout=3).json()["state"] == "READY"
                assert client.get(url=f"/v2/sessions/{sid}", headers=auth(token=access["access_token"])).json()["state"] == "READY"
                closing = pool.submit(client.delete, url=f"/v2/sessions/{sid}", headers=auth(token=access["access_token"]))
                assert control.receive_json()["type"] == "session_stop"
                report(control=control, generation=generation, session_id=sid, type="session_closed", cleanup="COMPLETE")
                assert closing.result(timeout=3).json()["cleanup"] == "COMPLETE"
