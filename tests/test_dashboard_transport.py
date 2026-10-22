"""实际 TCP/WebSocket 往返测量，不以 TestClient 或固定数字代替 RTT。"""

import asyncio
import json
import socket

import httpx
import uvicorn
from websockets.legacy.client import WebSocketClientProtocol, connect

from runbridge_hub.app import create_app
from runbridge_hub.settings import HubSettings
from runbridge_hub.transport import ControlWebSocketProtocol


class DelayedPong(WebSocketClientProtocol):
    """只在本测试的网络对端注入可验证的 35 毫秒延迟。"""

    async def pong(self, data=b""):
        """模拟链路往返延迟。

        :param data: 与 Ping 相同的载荷。
        """
        await asyncio.sleep(0.035)
        await super().pong(data=data)


async def test_real_ping_pong_disconnect_and_new_generation(tmp_path):
    enrollment, identity, web = "e" * 64, "n" * 64, "w" * 64
    app = create_app(settings=HubSettings(database_path=tmp_path / "hub.sqlite3", enrollment_token=enrollment, web_token=web))
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    port = listener.getsockname()[1]
    server = uvicorn.Server(config=uvicorn.Config(app=app, ws=ControlWebSocketProtocol, ws_ping_interval=0.05, ws_ping_timeout=1, log_level="error"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    task.result()
                await asyncio.sleep(0.01)
        async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", trust_env=False) as client:
            registered = await client.post(url="/v1/nodes/register", headers={"Authorization": f"Bearer {enrollment}"}, json={"node_id": "latency_node", "name": "真实 RTT 测试", "node_token": identity})
            assert registered.status_code == 201
            generations = []
            samples = []
            for _ in range(2):
                async with connect(uri=f"ws://127.0.0.1:{port}/v2/nodes/latency_node/control", extra_headers={"Authorization": f"Bearer {identity}"}, create_protocol=DelayedPong, ping_interval=None) as websocket:
                    welcome = json.loads(await websocket.recv())
                    generations.append(welcome["connection_generation"])
                    await websocket.send(json.dumps({"protocol_version": 2, "type": "capabilities", "connection_generation": generations[-1], "capabilities": {"host": {"test_fixture": "network-peer"}}}))
                    assert json.loads(await websocket.recv())["type"] == "capabilities_ack"
                    async with asyncio.timeout(3):
                        while True:
                            response = await client.get(url="/dashboard/api/nodes", headers={"Authorization": f"Bearer {web}"})
                            node = response.json()["nodes"][0]
                            if node["latency"]["status"] == "MEASURED":
                                break
                            await asyncio.sleep(0.01)
                    assert node["connection_status"] == "ONLINE"
                    assert node["latency"]["rtt_ms"] >= 30
                    assert node["latency"]["measured_at"] is not None
                    samples.append(node["latency"]["measured_at"])
                async with asyncio.timeout(3):
                    while True:
                        response = await client.get(url="/dashboard/api/nodes", headers={"Authorization": f"Bearer {web}"})
                        node = response.json()["nodes"][0]
                        if node["connection_status"] == "OFFLINE":
                            break
                        await asyncio.sleep(0.01)
                assert node["latency"]["rtt_ms"] is None
                assert node["latency"]["status"] == "OFFLINE"
            assert generations[1] > generations[0]
            assert samples[1] != samples[0]
    finally:
        server.should_exit = True
        await asyncio.wait_for(task, timeout=5)
        listener.close()
