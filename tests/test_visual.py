"""画面接口的会话权限、来源、新鲜度和有界分发验证。"""

import base64
import asyncio
import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager

import pytest
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketDenialResponse, WebSocketDisconnect

from runbridge_hub.app import create_app
from runbridge_hub.visual_protocol import VisualFrame
from runbridge_hub.visual_wire import pack_frame
from test_r1 import IDENTITY, auth, grant, register, settings
from test_sessions import report


PNG = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a3ioAAAAASUVORK5CYII=")


@contextmanager
def active_session(*, client, access, visual=True):
    """模拟节点执行，保持真正的 Hub 原生与控制连接。"""
    with ThreadPoolExecutor(max_workers=1) as pool, client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control:
        generation = control.receive_json()["connection_generation"]
        control.send_json({"type": "capabilities", "connection_generation": generation, "capabilities": {
            "backends": [{"name": "chrome-cdp", "runtime_version": "146.0.0.0", "coverage_status": "SUPPORTED",
                          "declared_protocols": ["cdp"] + (["runbridge-visual-v1"] if visual else [])}],
            "resources": [{"resource_id": "chrome", "backend": "chrome-cdp", "kind": "BORROWED_CHROME_CDP",
                           "authorization_scope": "BROWSER_INSTANCE", "readiness": "READY", "occupancy": "FREE"}]}})
        assert control.receive_json()["type"] == "capabilities_ack"
        future = pool.submit(client.post, url="/v1/nodes/node_a/sessions", headers=auth(token=access["access_token"]),
                             json={"resource_id": "chrome", "client_version": "1.63.0"})
        session_id = control.receive_json()["session_id"]
        headers = {**auth(token=IDENTITY), "x-runbridge-generation": str(generation)}
        with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{session_id}/tunnel", headers=headers) as tunnel:
            report(control=control, generation=generation, session_id=session_id, type="session_prepared", runtime_version="146.0.0.0")
            prepared = future.result(timeout=3).json()
            with client.websocket_connect(url=prepared["native_path"], headers={**auth(token=access["access_token"]), "User-Agent": "Playwright/1.63.0"}) as caller:
                assert control.receive_json()["type"] == "session_connect"
                try:
                    yield session_id, generation, headers, caller, tunnel
                finally:
                    caller.close()
                    current = client.app.state.sessions.sessions[session_id].view
                    if current.state not in {"CLOSED", "FAILED", "INTERRUPTED"} and current.cleanup != "COMPLETE":
                        assert control.receive_json()["type"] == "session_stop"
                        report(control=control, generation=generation, session_id=session_id, type="session_closed", cleanup="COMPLETE")


def wait_view(*, client, access, session_id, predicate):
    """只以公开查询确认异步接收状态，不假定 send 已处理。"""
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        value = client.get(url=f"/v1/sessions/{session_id}", headers=auth(token=access["access_token"])).json()
        if predicate(value):
            return value
        time.sleep(0.01)
    raise AssertionError("画面查询未达到预期状态")


def begin(*, upload, targets=None, stream_id="stream_a", target_id="target_a", request_id=None, browscreen_version="0.3.1"):
    """采集源的目录与首帧前状态。"""
    upload.send_json({"type": "hello", "browscreen_version": browscreen_version})
    upload.send_json({"type": "targets", "targets": targets or [{"target_id": "target_a", "label": "页面 1"}]})
    upload.send_json({"type": "state", "state": "WAITING", "stream_id": stream_id, "target_id": target_id, "request_id": request_id})


def frame(*, session_id, generation, frame_id=1, stream_id="stream_a", target_id="target_a"):
    """固定测试图；未来的来源墙钟不影响 Hub 新鲜度。"""
    return pack_frame(metadata=VisualFrame(session_id=session_id, resource_id="chrome", connection_generation=generation,
        stream_id=stream_id, target_id=target_id, frame_id=frame_id, capture_started_at="2099-01-01T00:00:00Z"), png=PNG)


def read_frame(*, subscriber):
    """状态消息和图片在同一订阅中独立保留类型。"""
    while True:
        event = subscriber.receive()
        if event.get("bytes") is not None:
            return event["bytes"]
        assert json.loads(event["text"])["type"] == "state"


@pytest.mark.parametrize("value", ["0.3.1", "0.3.2", "0.3.10"])
def test_upload_accepts_compatible_version_and_distributes_frame(tmp_path, value):
    """版本范围在真实上传路由生效，消费者仍可收到完整帧。"""
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, *_):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload, browscreen_version=value)
                data = frame(session_id=sid, generation=generation)
                upload.send_bytes(data=data)
                wait_view(client=client, access=access, session_id=sid, predicate=lambda view: view["visual"]["state"] == "LIVE")
                with client.websocket_connect(url=f"/v1/sessions/{sid}/visual/stream", headers=auth(token=access["access_token"])) as subscriber:
                    assert read_frame(subscriber=subscriber) == data


@pytest.mark.parametrize("value", ["0.3.0", "0.4.0", "0.3.2rc1", "invalid"])
def test_upload_rejects_unsupported_version_and_keeps_execution(tmp_path, value):
    """越界或预发布版本仅关闭画面通道，原生执行仍能传输。"""
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, _, headers, caller, tunnel):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                upload.send_json({"type": "hello", "browscreen_version": value})
                with pytest.raises(WebSocketDisconnect) as closed:
                    upload.receive_bytes()
                assert closed.value.code == 1008
                view = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()
                assert view["state"] == "ACTIVE" and view["visual"]["last_frame_id"] is None
                caller.send_text(data="execution remains active")
                assert tunnel.receive_text() == "execution remains active"


def test_queries_discover_stream_and_scope_grant(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access, other = grant(client=client), grant(client=client)
        assert client.get(url="/v1/nodes/node_a/visual/support", headers=auth(token=IDENTITY)).json()["visual_protocol_version"] == 1
        with active_session(client=client, access=access) as (sid, generation, headers, caller, tunnel):
            path = f"/v1/sessions/{sid}/visual/stream"
            own = client.get(url="/v1/nodes/node_a/capabilities", headers=auth(token=access["access_token"])).json()
            foreign = client.get(url="/v1/nodes/node_a", headers=auth(token=other["access_token"])).json()
            assert own["visual"]["streams"][0]["stream_path"] == path
            assert foreign["visual"]["supported"] and foreign["visual"]["streams"] == []
            for token, status in (("wrong", 401), (other["access_token"], 403)):
                with pytest.raises(WebSocketDenialResponse) as denied:
                    with client.websocket_connect(url=path, headers=auth(token=token)):
                        pass
                assert denied.value.status_code == status
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload)
                data = frame(session_id=sid, generation=generation)
                upload.send_bytes(data=data)
                live = wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "LIVE")
                assert live["visual"]["last_frame_id"] == 1 and live["visual"]["frame_age_ms"] < 1000
                assert "visual" not in client.app.state.sessions.sessions[sid].view.model_dump()
                with client.websocket_connect(url=path, headers=auth(token=access["access_token"])) as first, client.websocket_connect(url=path) as browser:
                    assert read_frame(subscriber=first) == data
                    browser.send_json({"type": "auth", "access_token": access["access_token"]})
                    assert read_frame(subscriber=browser) == data
                    caller.send_text(data='{"method":"independent_execution"}')
                    assert tunnel.receive_text() == '{"method":"independent_execution"}'


def test_target_switch_freezes_old_stream_and_confirms_first_frame(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, caller, tunnel):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                targets = [{"target_id": f"target_{value}", "label": f"页面 {index}"} for index, value in enumerate(("a", "b"), start=1)]
                begin(upload=upload, targets=targets)
                upload.send_bytes(data=frame(session_id=sid, generation=generation))
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "LIVE")
                result = client.put(url=f"/v1/sessions/{sid}/visual/target", headers=auth(token=access["access_token"]), json={"target_id": "target_b"})
                assert result.status_code == 202
                request_id = result.json()["request_id"]
                assert upload.receive_json()["request_id"] == request_id
                busy = client.put(url=f"/v1/sessions/{sid}/visual/target", headers=auth(token=access["access_token"]), json={"target_id": "target_a"})
                assert busy.status_code == 409
                upload.send_bytes(data=frame(session_id=sid, generation=generation, frame_id=2))
                upload.send_json({"type": "state", "state": "WAITING", "request_id": request_id, "stream_id": "stream_b", "target_id": "target_b"})
                upload.send_bytes(data=frame(session_id=sid, generation=generation, stream_id="stream_b", target_id="target_b"))
                changed = wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["selection"]["state"] == "APPLIED")
                assert changed["visual"]["stream_id"] == "stream_b" and changed["visual"]["last_frame_id"] == 1
                upload.send_bytes(data=frame(session_id=sid, generation=generation, frame_id=99))
                upload.send_bytes(data=frame(session_id=sid, generation=generation, stream_id="stream_b", target_id="target_b"))
                assert client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()["visual"]["last_frame_id"] == 1
                upload.send_json({"type": "targets", "targets": targets[:1]})
                closed = wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "WAITING_TARGET")
                assert closed["visual"]["target_id"] is None


@pytest.mark.parametrize("invalid", ["generation", "session", "png", "header", "live_claim"])
def test_invalid_upload_isolated_from_execution(tmp_path, invalid):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, caller, tunnel):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload)
                if invalid == "live_claim":
                    upload.send_json({"type": "state", "state": "LIVE"})
                elif invalid == "header":
                    upload.send_bytes(data=b"\xff\xff\xff\xff")
                elif invalid == "png":
                    upload.send_bytes(data=frame(session_id=sid, generation=generation)[:-len(PNG)] + b"not PNG")
                else:
                    upload.send_bytes(data=frame(session_id="another_session" if invalid == "session" else sid,
                                                 generation=generation + 1 if invalid == "generation" else generation))
                with pytest.raises(WebSocketDisconnect):
                    upload.receive_bytes()
                value = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()
                assert value["state"] == "ACTIVE"
                caller.send_text(data="execution remains active")
                assert tunnel.receive_text() == "execution remains active"


def test_unavailable_old_node_does_not_advertise_connection(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access, visual=False) as (sid, *_):
            value = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()["visual"]
            assert not value["supported"] and value["stream_path"] is None
            assert value["reason_code"] == "EXTENSION_NOT_ADVERTISED"


def test_stale_frame_and_slow_queue_remain_bounded(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, *_):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload)
                upload.send_bytes(data=frame(session_id=sid, generation=generation))
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "LIVE")

                def congest_and_expire():
                    import asyncio
                    service = client.app.state.visual
                    channel = service.channels[sid]
                    queue = asyncio.Queue(maxsize=1)
                    channel.subscribers[queue] = None
                    for _ in range(100):
                        service.publish(channel=channel)
                    assert queue.qsize() == 1
                    channel.received_at -= 6
                    service.refresh(channel=channel)
                    assert queue.get_nowait()[1] is None and channel.packet is None
                    channel.subscribers.pop(queue)

                client.portal.call(congest_and_expire)
                value = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()["visual"]
                assert value["state"] == "STALE" and value["frame_age_ms"] >= 6000


def test_revocation_closes_subscriptions_and_clears_cache(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, *_):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload)
                data = frame(session_id=sid, generation=generation)
                upload.send_bytes(data=data)
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "LIVE")
                with client.websocket_connect(url=f"/v1/sessions/{sid}/visual/stream", headers=auth(token=access["access_token"])) as subscriber:
                    assert read_frame(subscriber=subscriber) == data
                    response = client.delete(url=f"/v1/nodes/node_a/grants/{access['grant_id']}", headers=auth(token=IDENTITY))
                    assert response.status_code == 204
                    with pytest.raises(WebSocketDisconnect):
                        subscriber.receive_bytes()
                    with pytest.raises(WebSocketDisconnect):
                        upload.receive_bytes()
                    assert sid not in client.app.state.visual.channels
                    assert client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).status_code == 401


def test_reconnect_preserves_selected_source_and_sequence_floor(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, *_):
            path = f"/v1/nodes/node_a/sessions/{sid}/visual/upload"
            with client.websocket_connect(url=path, headers=headers) as upload:
                begin(upload=upload)
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["target_id"] == "target_a")
                result = client.put(url=f"/v1/sessions/{sid}/visual/target", headers=auth(token=access["access_token"]), json={"target_id": "target_a"})
                rid = upload.receive_json()["request_id"]
                assert result.status_code == 202
                upload.send_json({"type": "state", "state": "WAITING", "request_id": rid, "stream_id": "stream_b", "target_id": "target_a"})
                upload.send_bytes(data=frame(session_id=sid, generation=generation, frame_id=5, stream_id="stream_b"))
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["last_frame_id"] == 5)
                upload.send_json({"type": "state", "state": "ERROR", "request_id": rid, "stream_id": "stream_b", "target_id": "target_a", "reason_code": "CAPTURE_FAILED"})
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "ERROR")
                upload.send_bytes(data=frame(session_id=sid, generation=generation, frame_id=5, stream_id="stream_b"))
                assert client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()["visual"]["state"] == "ERROR"
            wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["reason_code"] == "VISUAL_UPLOAD_DISCONNECTED")
            with client.websocket_connect(url=path, headers=headers) as upload:
                begin(upload=upload, stream_id="stream_b", request_id=rid)
                upload.send_bytes(data=frame(session_id=sid, generation=generation, frame_id=6, stream_id="stream_b"))
                live = wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "LIVE")
                assert live["visual"]["last_frame_id"] == 6 and live["visual"]["selection"]["state"] == "APPLIED"


def test_expired_selection_does_not_accept_late_confirmation(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, *_):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload)
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["target_id"] == "target_a")
                result = client.put(url=f"/v1/sessions/{sid}/visual/target", headers=auth(token=access["access_token"]), json={"target_id": "target_a"})
                assert result.status_code == 202
                rid = upload.receive_json()["request_id"]

                def expire():
                    client.app.state.visual.channels[sid].selection_started_at -= 11

                client.portal.call(expire)
                failed = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()["visual"]
                assert failed["selection"]["state"] == "FAILED"
                upload.send_json({"type": "state", "state": "WAITING", "request_id": rid, "stream_id": "stream_late", "target_id": "target_a"})
                upload.send_bytes(data=frame(session_id=sid, generation=generation, stream_id="stream_late"))
                actual = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()["visual"]
                assert actual["stream_id"] is None and actual["state"] == "ERROR"


def test_replaced_control_generation_retires_visual_channel(tmp_path):
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, generation, headers, *_):
            with client.websocket_connect(url=f"/v1/nodes/node_a/sessions/{sid}/visual/upload", headers=headers) as upload:
                begin(upload=upload)
                upload.send_bytes(data=frame(session_id=sid, generation=generation))
                wait_view(client=client, access=access, session_id=sid, predicate=lambda value: value["visual"]["state"] == "LIVE")
                with client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as replacement:
                    assert replacement.receive_json()["connection_generation"] > generation
                    with pytest.raises(WebSocketDisconnect):
                        upload.receive_bytes()
                    assert sid not in client.app.state.visual.channels
                    value = client.get(url=f"/v1/sessions/{sid}", headers=auth(token=access["access_token"])).json()
                    assert value["cleanup"] == "UNKNOWN" and value["visual"]["stream_path"] is None


def test_slow_visual_cleanup_does_not_delay_native_disconnect(tmp_path):
    """画面清理仍被阻塞时，原生调用方必须已收到关闭。"""
    with TestClient(app=create_app(settings=settings(tmp_path=tmp_path))) as client:
        register(client=client)
        access = grant(client=client)
        with active_session(client=client, access=access) as (sid, _, _, caller, _):
            service = client.app.state.sessions
            entered = threading.Event()
            release = asyncio.Event()

            async def delayed_visual(*, session_id, reason):
                await client.app.state.visual.close(session_id=session_id, reason=reason)
                entered.set()
                await release.wait()

            async def close():
                await service.close(session=service.sessions[sid], reason="TEST_SLOW_VISUAL_CLEANUP")

            service.on_close = delayed_visual
            operation = client.portal.start_task_soon(close)
            try:
                assert entered.wait(timeout=2)
                with ThreadPoolExecutor(max_workers=1) as pool:
                    received = pool.submit(caller.receive)
                    try:
                        assert received.result(timeout=1)["type"] == "websocket.close"
                    finally:
                        client.portal.call(release.set)
            finally:
                client.portal.call(release.set)
                operation.result(timeout=3)
                service.on_close = client.app.state.visual.close
