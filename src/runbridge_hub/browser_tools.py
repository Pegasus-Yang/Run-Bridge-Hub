"""MCP 参数转换；定位与页面操作均由 Node 执行。"""

import re
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

from runbridge_hub.browser import BrowserError
from runbridge_hub.protocol import Identifier
from runbridge_hub.tool_contract import (
    CaptureDefinition as Capture,
    Target as ObjectTarget,
    UploadFile,
)


Timeout = Annotated[int, Field(ge=1, le=30000)]


class Target(BaseModel):
    model_config = ConfigDict(extra="forbid")
    by: Literal["role", "label", "text", "test_id", "css"]
    value: str = Field(min_length=1, max_length=2000)
    name: str | None = Field(default=None, max_length=2000)
    frame_selector: str | None = Field(default=None, min_length=1, max_length=2000)


def object_target(*, page_id: str, target: Target | None = None) -> ObjectTarget:
    """把已有 MCP 定位参数转换为声明式步骤，不创建 Locator。"""
    steps = []
    if target is not None:
        if target.frame_selector:
            steps.append(
                {
                    "method": "frame_locator",
                    "params": {"selector": f"css={target.frame_selector}"},
                }
            )
        if target.by == "role":
            if re.fullmatch(r"[a-z]+", target.value) is None:
                raise BrowserError(code="INVALID_ROLE")
            method, params = (
                "get_by_role",
                {"role": target.value, "name": target.name, "exact": True},
            )
        elif target.by in {"label", "text"}:
            method, params = (
                f"get_by_{target.by}",
                {"text": target.value, "exact": True},
            )
        elif target.by == "test_id":
            method, params = "get_by_test_id", {"test_id": target.value}
        else:
            method, params = "locator", {"selector": f"css={target.value}"}
        steps.append({"method": method, "params": params})
    return ObjectTarget(type="page", id=page_id, locator=steps)


def register_tools(*, tool, browsers, token):
    async def call(*, session_id, page_id, method, params, target=None):
        return await browsers().call(
            session_id=session_id,
            token=token(),
            method=method,
            target=object_target(page_id=page_id, target=target),
            params=params,
        )

    @tool(readonly=True, idempotent=True)
    async def browser_inspect_dom(
        session_id: Identifier,
        page_id: Identifier,
        selector: Annotated[
            str, Field(min_length=1, max_length=2000)
        ] = "input,textarea,select,button,a,iframe",
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """固定只读查看 DOM；实际采集在 Node，最多 200 项。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="runbridge.inspect_dom",
            params={"selector": selector, "timeout": timeout_ms},
        )

    @tool(readonly=True, idempotent=True)
    async def browser_capture(
        session_id: Identifier,
        page_id: Identifier,
        captures: Annotated[dict[str, Capture], Field(min_length=1, max_length=128)],
        allowed_origins: Annotated[list[str], Field(min_length=1, max_length=64)],
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """Node 按固定 DOM 合同采集并在同次读取检查来源，不接受脚本。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="runbridge.capture",
            params={
                "captures": {
                    name: value.model_dump(exclude_none=True)
                    for name, value in captures.items()
                },
                "allowed_origins": allowed_origins,
                "timeout": timeout_ms,
            },
        )

    @tool()
    async def browser_press_key(
        session_id: Identifier,
        page_id: Identifier,
        key: Annotated[str, Field(min_length=1, max_length=128)],
        target: Target | None = None,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """向指定元素或当前页面按键。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.press" if target else "page.keyboard.press",
            target=target,
            params={"key": key, "timeout": timeout_ms},
        )

    @tool()
    async def browser_select_option(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        values: Annotated[list[str], Field(min_length=1, max_length=128)],
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """按 value 选择选项并返回实际选中值。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.select_option",
            target=target,
            params={"value": values, "timeout": timeout_ms},
        )

    @tool()
    async def browser_check(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        checked: bool,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """设置明确选中状态，再读取实际状态。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.set_checked",
            target=target,
            params={"checked": checked, "timeout": timeout_ms},
        )

    @tool()
    async def browser_hover(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """悬停唯一匹配元素，保留 Playwright 可操作检查。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.hover",
            target=target,
            params={"timeout": timeout_ms},
        )

    @tool()
    async def browser_drag(
        session_id: Identifier,
        page_id: Identifier,
        source: Target,
        target: Target,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """明确源与目标均唯一匹配时拖拽。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.drag_to",
            target=source,
            params={
                "target": object_target(page_id=page_id, target=target).model_dump(),
                "timeout": timeout_ms,
            },
        )

    @tool()
    async def browser_scroll(
        session_id: Identifier,
        page_id: Identifier,
        delta_x: int = 0,
        delta_y: int = 600,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """在当前页面发送指定滚轮动作。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="page.mouse.wheel",
            params={"delta_x": delta_x, "delta_y": delta_y, "timeout": timeout_ms},
        )

    @tool()
    async def browser_navigate_back(
        session_id: Identifier, page_id: Identifier, timeout_ms: Timeout = 10000
    ) -> dict:
        """返回历史并等待 DOM 就绪。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="page.go_back",
            params={"timeout": timeout_ms},
        )

    @tool()
    async def browser_resize(
        session_id: Identifier,
        page_id: Identifier,
        width: Annotated[int, Field(ge=320, le=4096)],
        height: Annotated[int, Field(ge=200, le=4096)],
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """显式调整当前页面视口。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="page.set_viewport_size",
            params={
                "viewport_size": {"width": width, "height": height},
                "timeout": timeout_ms,
            },
        )

    @tool(readonly=True, idempotent=True)
    async def browser_frames(
        session_id: Identifier, page_id: Identifier, timeout_ms: Timeout = 10000
    ) -> dict:
        """列出 frame 名称与 URL；操作时仍需明确 iframe selector。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="page.frames",
            params={"timeout": timeout_ms},
        )

    @tool()
    async def browser_tabs(
        session_id: Identifier,
        action: Literal["list", "new", "select", "close"] = "list",
        page_id: Identifier | None = None,
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """管理本会话标签页，选页同时切换实际画面。"""
        value = await browsers().call(
            session_id=session_id,
            token=token(),
            method="runbridge.tabs",
            target=ObjectTarget(type="session", id=session_id),
            params={"action": action, "page_id": page_id, "timeout": timeout_ms},
        )
        return {
            **(await browsers().status(session_id=session_id, token=token())),
            **value,
        }

    @tool()
    async def browser_handle_dialog(
        session_id: Identifier,
        page_id: Identifier,
        accept: bool,
        prompt_text: Annotated[str | None, Field(max_length=20000)] = None,
    ) -> dict:
        """预先设置一次性弹窗策略，默认 dismiss。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="runbridge.dialog_policy",
            params={"accept": accept, "prompt_text": prompt_text},
        )

    @tool()
    async def browser_file_upload(
        session_id: Identifier,
        page_id: Identifier,
        target: Target,
        files: Annotated[list[UploadFile], Field(max_length=32)],
        timeout_ms: Timeout = 10000,
    ) -> dict:
        """上传显式 base64 数据；Node 解码后合计最多 4 MiB，空列表清空。"""
        return await call(
            session_id=session_id,
            page_id=page_id,
            method="locator.set_input_files",
            target=target,
            params={
                "files": [file.model_dump() for file in files],
                "timeout": timeout_ms,
            },
        )
