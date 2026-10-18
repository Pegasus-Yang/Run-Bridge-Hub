"""两端同一份版本化样例，检查参数默认值、定位描述和去重摘要。"""

import json
from pathlib import Path
import pytest
from pydantic import ValidationError
from runbridge_hub.tool_contract import (
    CommandInput,
    METHODS,
    OUTPUTS,
    Target,
    ToolResult,
    catalog,
    fingerprint,
    validate_call,
)

DATA = json.loads((Path(__file__).parent / "fixtures/tool-api-v1.json").read_text())


@pytest.mark.parametrize("sample", DATA["samples"])
def test_contract_sample_matches_versioned_fixture(sample):
    request = CommandInput.model_validate(sample["request"])
    _, params = validate_call(request=request)
    request = request.model_copy(update={"params": params.model_dump(mode="json")})
    assert request.params == sample["normalized_params"]
    assert fingerprint(request=request) == sample["fingerprint"]


def test_every_method_declares_input_output_and_bounded_timeout():
    assert len(METHODS) == 33 and METHODS.keys() == OUTPUTS.keys()
    for method, schema in catalog().items():
        assert schema["parameters"]["properties"]["timeout"]["default"] == 10000
        assert schema["parameters"]["additionalProperties"] is False
        assert schema["result"]


@pytest.mark.parametrize(
    "steps",
    [
        [{"method": "evaluate", "params": {"script": "x"}}],
        [{"method": "frame_locator", "params": {"selector": "iframe"}}],
        [{"method": "locator", "params": {"selector": "#x", "unknown": True}}],
    ],
)
def test_locator_rejects_unknown_steps_or_arguments(steps):
    with pytest.raises(ValidationError):
        Target(type="page", id="page_a", locator=steps)


def test_success_result_cannot_lie_about_unknown_outcome():
    with pytest.raises(ValidationError):
        ToolResult(
            session_id="session_a",
            connection_generation=1,
            request_id="request_a",
            status="SUCCEEDED",
            execution_outcome="OUTCOME_UNKNOWN",
            result={"kind": "json", "value": "value"},
        )


def test_drag_destination_must_be_a_page_locator():
    request=CommandInput(request_id="drag",method="locator.drag_to",target=Target(type="page",id="page_a",locator=[{"method":"locator","params":{"selector":"#source"}}]),params={"target":{"type":"page","id":"page_a"}})
    with pytest.raises(ValidationError):
        validate_call(request=request)
