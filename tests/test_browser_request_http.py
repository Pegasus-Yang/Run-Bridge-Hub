"""MCP HTTP 入口验证失败启动的身份恢复合同。"""

from concurrent.futures import ThreadPoolExecutor

import pytest

from test_mcp import call, mcp_client
from test_r1 import IDENTITY, auth, grant
from test_sessions import publish, report


@pytest.mark.parametrize("protocol", ["2025-11-25", "2026-07-28"])
def test_http_prepare_failure_keeps_request_session_and_unknown_cleanup(mcp_client, protocol):
    access = grant(client=mcp_client)
    with mcp_client.websocket_connect(url="/v1/nodes/node_a/control", headers=auth(token=IDENTITY)) as control, ThreadPoolExecutor(max_workers=1) as pool:
        generation = publish(websocket=control)
        arguments = {"node_id": "node_a", "request_id": "http_request", "resource_id": "chromium", "lease_seconds": 30}
        starting = pool.submit(call, client=mcp_client, token=access["access_token"], name="browser_start", arguments=arguments, protocol=protocol)
        opened = control.receive_json()
        session_id = opened["session_id"]
        querying = {"node_id": "node_a", "request_id": "http_request"}
        pending = call(client=mcp_client, token=access["access_token"], name="browser_sessions", arguments=querying, protocol=protocol)["structuredContent"]
        assert pending["request"]["state"] == "PENDING"
        assert pending["request"]["session_id"] == session_id
        assert pending["sessions"][0]["session"]["state"] == "PREPARING"
        report(control=control, generation=generation, session_id=session_id, type="session_prepared", error_code="PLAYWRIGHT_LAUNCH_FAILED")
        report(control=control, generation=generation, session_id=session_id, type="session_closed", cleanup="UNKNOWN")
        failure = starting.result(timeout=3)
        assert failure["isError"] and failure["structuredContent"]["execution_outcome"] == "OUTCOME_UNKNOWN"
        value = call(client=mcp_client, token=access["access_token"], name="browser_sessions", arguments=querying, protocol=protocol)["structuredContent"]
        assert value["request"] == {"request_id": "http_request", "node_id": "node_a", "grant_id": access["grant_id"], "state": "FAILED", "session_id": session_id, "error_code": "PLAYWRIGHT_LAUNCH_FAILED", "execution_outcome": "OUTCOME_UNKNOWN"}
        assert value["sessions"][0]["request_id"] == "http_request"
        assert value["sessions"][0]["session"]["cleanup"] == "UNKNOWN"
        assert value["sessions"][0]["session"]["session_id"] == session_id
        assert access["access_token"] not in str(value)


def test_http_does_not_confuse_unallocated_failure_and_missing_request(mcp_client):
    access = grant(client=mcp_client)
    args = {"node_id": "node_a", "request_id": "offline_request"}
    failure = call(client=mcp_client, token=access["access_token"], name="browser_start", arguments=args)
    assert failure["structuredContent"] == {"code": "NODE_OFFLINE", "execution_outcome": "NOT_STARTED"}
    value = call(client=mcp_client, token=access["access_token"], name="browser_sessions", arguments=args)["structuredContent"]
    assert value["request"]["state"] == "FAILED" and value["request"]["session_id"] is None
    assert value["request"]["execution_outcome"] == "NOT_STARTED" and value["sessions"] == []
    missing = call(client=mcp_client, token=access["access_token"], name="browser_sessions", arguments={**args, "request_id": "missing"})["structuredContent"]
    assert missing["request"]["state"] == "NOT_FOUND"
    assert missing["request"]["execution_outcome"] is None
