"""工具调用的公开合同；两端发行物保存相同的版本化声明。"""

import hashlib
import json
from dataclasses import dataclass
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    TypeAdapter,
    model_validator,
)


Identifier = Annotated[
    str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
]
TOOL_API_VERSION = 1
MAX_MESSAGE = 16 * 1024 * 1024


class Contract(BaseModel):
    """禁止遗漏或拼错的协议参数。"""

    model_config = ConfigDict(extra="forbid")


class LocatorStep(Contract):
    method: Literal[
        "frame_locator",
        "locator",
        "get_by_role",
        "get_by_label",
        "get_by_text",
        "get_by_test_id",
    ]
    params: dict[str, JsonValue]

    @model_validator(mode="after")
    def known_arguments(self):
        allowed = {
            "frame_locator": {"selector"},
            "locator": {"selector"},
            "get_by_role": {"role", "name", "exact"},
            "get_by_label": {"text", "exact"},
            "get_by_text": {"text", "exact"},
            "get_by_test_id": {"test_id"},
        }[self.method]
        required = {
            "frame_locator": "selector",
            "locator": "selector",
            "get_by_role": "role",
            "get_by_label": "text",
            "get_by_text": "text",
            "get_by_test_id": "test_id",
        }[self.method]
        if (
            set(self.params) - allowed
            or not isinstance(self.params.get(required), str)
            or not 0 < len(self.params[required]) <= 2000
        ):
            raise ValueError("定位参数无效")
        if "exact" in self.params and not isinstance(self.params["exact"], bool):
            raise ValueError("exact 必须是布尔值")
        if self.params.get("name") is not None and (
            not isinstance(self.params["name"], str) or len(self.params["name"]) > 2000
        ):
            raise ValueError("name 无效")
        return self


class Target(Contract):
    type: Identifier
    id: Identifier
    locator: list[LocatorStep] = Field(default_factory=list, max_length=16)

    @model_validator(mode="after")
    def page_locator(self):
        if self.locator and self.type != "page":
            raise ValueError("定位步骤需要 Page 引用")
        if self.locator and self.locator[-1].method == "frame_locator":
            raise ValueError("frame_locator 后还需要元素定位步骤")
        return self


class CommandInput(Contract):
    request_id: Identifier
    method: str = Field(min_length=1, max_length=128)
    target: Target
    params: dict[str, JsonValue] = Field(default_factory=dict)


class Execute(CommandInput):
    protocol_version: Literal[2] = 2
    type: Literal["execute"] = "execute"
    session_id: Identifier
    connection_generation: int = Field(ge=1)
    tool: Identifier = "playwright"
    tool_api_version: int = TOOL_API_VERSION
    remaining_ms: int = Field(ge=1, le=30000)


class Params(Contract):
    timeout: int = Field(default=10000, ge=1, le=30000)


class Navigate(Params):
    url: str = Field(min_length=1, max_length=8192)
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = (
        "domcontentloaded"
    )


class Back(Params):
    wait_until: Literal["commit", "domcontentloaded", "load", "networkidle"] = (
        "domcontentloaded"
    )


class Fill(Params):
    value: str = Field(max_length=20000)


class Click(Params):
    button: Literal["left", "right", "middle"] = "left"


class Press(Params):
    key: str = Field(min_length=1, max_length=128)


class SelectOption(Params):
    value: list[str] = Field(min_length=1, max_length=128)


class Checked(Params):
    checked: bool


class Drag(Params):
    target: Target

    @model_validator(mode="after")
    def element_target(self):
        if self.target.type != "page" or not self.target.locator:
            raise ValueError("拖拽目标必须为 Page 下的元素定位")
        return self


class Wait(Params):
    state: Literal["visible", "hidden", "attached", "detached"] = "visible"


class WaitValue(Params):
    state: Literal["text", "value"]
    value: str = Field(max_length=20000)


class Wheel(Params):
    delta_x: int = 0
    delta_y: int = 600


class Viewport(Contract):
    width: int = Field(ge=320, le=4096)
    height: int = Field(ge=200, le=4096)


class ContextOptions(Params):
    viewport: Viewport = Field(default_factory=lambda: Viewport(width=1280, height=720))
    locale: str = Field(default="zh-CN", min_length=1, max_length=64)


class Resize(Params):
    viewport_size: Viewport


class Screenshot(Params):
    full_page: bool = False


class InspectDOM(Params):
    selector: str = Field(
        default="input,textarea,select,button,a,iframe", min_length=1, max_length=2000
    )


class CaptureDefinition(Contract):
    kind: Literal["dom"] = "dom"
    mode: Literal["text", "number", "count", "visible", "url", "attribute", "value"] = (
        "text"
    )
    selector: str | None = Field(default=None, min_length=1, max_length=2000)
    attribute: str | None = Field(default=None, min_length=1, max_length=256)
    field: str | None = Field(default=None, max_length=256)
    index: int | None = Field(default=None, ge=0, le=100000)


class CaptureDOM(Params):
    captures: dict[str, CaptureDefinition] = Field(min_length=1, max_length=128)
    allowed_origins: list[str] = Field(min_length=1, max_length=64)


class Tabs(Params):
    action: Literal["list", "new", "select", "close"] = "list"
    page_id: Identifier | None = None


class DialogPolicy(Params):
    accept: bool
    prompt_text: str | None = Field(default=None, max_length=20000)


class UploadFile(Contract):
    name: str = Field(min_length=1, max_length=256, pattern=r"^[^/\\]+$")
    mime_type: str = Field(min_length=1, max_length=128)
    data: str = Field(max_length=6 * 1024 * 1024)


class Upload(Params):
    files: list[UploadFile] = Field(max_length=32)


class ObjectRef(Contract):
    type: Literal["browser", "context", "page"]
    id: Identifier


class Completed(Contract):
    completed: Literal[True] = True
    url: str | None = None
    state: str | None = None


class NavigationResult(Contract):
    url: str
    title: str
    http_status: int | None


class TextResult(Contract):
    value: str
    truncated: bool


class PageState(ObjectRef):
    page_id: Identifier
    context_id: Identifier | None
    url: str


class SessionState(Contract):
    root: ObjectRef | None
    contexts: list[ObjectRef]
    pages: list[PageState]
    default_page_id: Identifier | None
    ownership: Literal["managed", "borrowed"]
    last_dialog: dict[str, dict[str, JsonValue]]
    page_id: Identifier | None = None


class SnapshotResult(Contract):
    url: str
    title: str
    snapshot: str
    truncated: bool


class CaptureResult(Contract):
    values: dict[str, JsonValue]
    url: str
    title: str
    truncated: bool


class InspectResult(Contract):
    url: str
    elements: list[dict[str, JsonValue]]
    truncated: bool


class JsonResult(Contract):
    kind: Literal["json"]
    value: JsonValue


class BinaryResult(Contract):
    kind: Literal["binary"]
    mime_type: Literal["image/png"]
    encoding: Literal["base64"]
    size: int = Field(ge=1, le=2 * 1024 * 1024)
    data: str = Field(max_length=3 * 1024 * 1024)


class ToolFailure(Contract):
    code: Identifier
    message: str = "工具操作未完成"
    stage: str = "execute"
    retryable: Literal[False] = False


class ToolResult(Contract):
    protocol_version: Literal[2] = 2
    type: Literal["result"] = "result"
    request_id: Identifier
    session_id: Identifier
    connection_generation: int = Field(ge=1)
    status: Literal["SUCCEEDED", "FAILED", "UNKNOWN"]
    execution_outcome: Literal["NOT_STARTED", "COMPLETED", "OUTCOME_UNKNOWN"]
    result: JsonResult | BinaryResult | None = None
    error: ToolFailure | None = None

    @model_validator(mode="after")
    def result_matches_status(self):
        if self.status == "SUCCEEDED" and (
            self.result is None
            or self.error is not None
            or self.execution_outcome != "COMPLETED"
        ):
            raise ValueError("成功结果必须具有内容且已完成")
        if self.status != "SUCCEEDED" and (
            self.error is None or self.result is not None
        ):
            raise ValueError("失败结果必须具有错误码")
        return self


@dataclass(frozen=True)
class Method:
    """一项显式动作的参数模型、目标与写入标记。"""

    params: type[Params]
    target: str
    mutating: bool = False


METHODS = {
    "browser.contexts": Method(params=Params, target="browser"),
    "browser.new_context": Method(
        params=ContextOptions, target="browser", mutating=True
    ),
    "context.pages": Method(params=Params, target="context"),
    "context.new_page": Method(params=Params, target="context", mutating=True),
    "context.close": Method(params=Params, target="context", mutating=True),
    "page.goto": Method(params=Navigate, target="page", mutating=True),
    "page.go_back": Method(params=Back, target="page", mutating=True),
    "page.title": Method(params=Params, target="page"),
    "page.url": Method(params=Params, target="page"),
    "page.frames": Method(params=Params, target="page"),
    "page.close": Method(params=Params, target="page", mutating=True),
    "page.aria_snapshot": Method(params=Params, target="page"),
    "page.screenshot": Method(params=Screenshot, target="page"),
    "page.set_viewport_size": Method(params=Resize, target="page", mutating=True),
    "page.keyboard.press": Method(params=Press, target="page", mutating=True),
    "page.mouse.wheel": Method(params=Wheel, target="page", mutating=True),
    "locator.fill": Method(params=Fill, target="locator", mutating=True),
    "locator.click": Method(params=Click, target="locator", mutating=True),
    "locator.press": Method(params=Press, target="locator", mutating=True),
    "locator.hover": Method(params=Params, target="locator", mutating=True),
    "locator.select_option": Method(
        params=SelectOption, target="locator", mutating=True
    ),
    "locator.set_checked": Method(params=Checked, target="locator", mutating=True),
    "locator.drag_to": Method(params=Drag, target="locator", mutating=True),
    "locator.inner_text": Method(params=Params, target="locator"),
    "locator.input_value": Method(params=Params, target="locator"),
    "locator.wait_for": Method(params=Wait, target="locator"),
    "locator.set_input_files": Method(params=Upload, target="locator", mutating=True),
    "runbridge.inspect_dom": Method(params=InspectDOM, target="page"),
    "runbridge.capture": Method(params=CaptureDOM, target="page"),
    "runbridge.wait_for": Method(params=WaitValue, target="locator"),
    "runbridge.tabs": Method(params=Tabs, target="session", mutating=True),
    "runbridge.dialog_policy": Method(params=DialogPolicy, target="page"),
    "runbridge.session_state": Method(params=Params, target="session"),
}


TOOL_METHODS = {"playwright": METHODS}


def validate_call(
    *, request: CommandInput, tool: str = "playwright"
) -> tuple[Method, Params]:
    """校验公开动作和目标；不进行任意 Python 反射。

    :returns: 动作说明与已填默认值的参数。
    """
    method = TOOL_METHODS.get(tool, {}).get(request.method)
    if method is None:
        raise ValueError("METHOD_UNSUPPORTED")
    kind = "locator" if request.target.locator else request.target.type
    if kind != method.target:
        raise ValueError("OBJECT_TYPE_MISMATCH")
    return method, method.params.model_validate(request.params)


def fingerprint(*, request: CommandInput) -> str:
    """去重摘要不包含剩余预算和网络元数据。"""
    value = {
        "method": request.method,
        "target": request.target.model_dump(),
        "params": request.params,
    }
    return hashlib.sha256(
        json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def catalog(*, tool: str = "playwright") -> dict:
    """返回可公开的参数和结果规则，不包含本机运行配置。"""
    return {
        name: {
            "target": spec.target,
            "mutating": spec.mutating,
            "parameters": spec.params.model_json_schema(),
            "result": TypeAdapter(OUTPUTS[name]).json_schema(),
            "envelope": "binary" if name == "page.screenshot" else "json",
        }
        for name, spec in TOOL_METHODS.get(tool, {}).items()
    }


OUTPUTS = {
    "browser.contexts": list[ObjectRef],
    "browser.new_context": ObjectRef,
    "context.pages": list[ObjectRef],
    "context.new_page": ObjectRef,
    "context.close": Completed,
    "page.goto": NavigationResult,
    "page.go_back": dict[str, str],
    "page.title": str,
    "page.url": str,
    "page.frames": dict[str, list[dict[str, str]]],
    "page.close": Completed,
    "page.aria_snapshot": SnapshotResult,
    "page.screenshot": BinaryResult,
    "page.set_viewport_size": Viewport,
    "page.keyboard.press": Completed,
    "page.mouse.wheel": Completed,
    "locator.fill": Completed,
    "locator.click": Completed,
    "locator.press": Completed,
    "locator.hover": Completed,
    "locator.select_option": dict[str, list[str]],
    "locator.set_checked": dict[str, bool],
    "locator.drag_to": Completed,
    "locator.inner_text": TextResult,
    "locator.input_value": TextResult,
    "locator.wait_for": Completed,
    "locator.set_input_files": dict[str, list[str]],
    "runbridge.inspect_dom": InspectResult,
    "runbridge.capture": CaptureResult,
    "runbridge.wait_for": Completed,
    "runbridge.tabs": SessionState,
    "runbridge.dialog_policy": dict[str, bool],
    "runbridge.session_state": SessionState,
}


def validate_output(*, method: str, result: dict) -> None:
    """在 Node 返回前验证公开结果模型，避免适配器静默改变合同。"""
    TypeAdapter(OUTPUTS[method]).validate_python(
        result if method == "page.screenshot" else result["value"]
    )
