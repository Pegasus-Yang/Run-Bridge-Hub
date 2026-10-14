"""MCP 原子交互与固定只读采集，不接受调用方脚本。"""

import base64
import json
import re
from typing import Annotated, Literal
from urllib.parse import urlsplit

from playwright.async_api import Page
from pydantic import BaseModel, ConfigDict, Field

from runbridge_hub.browser import BrowserError
from runbridge_hub.protocol import Identifier


Timeout = Annotated[int, Field(ge=1, le=30000)]
UPLOAD_LIMIT = 4 * 1024 * 1024


class Target(BaseModel):
    """在本次页面或明确 iframe 中使用唯一定位。"""

    model_config = ConfigDict(extra="forbid")
    by: Literal["role", "label", "text", "test_id", "css"]
    value: str = Field(min_length=1, max_length=2000, description="role 时仅填 button、textbox 等角色；CSS 时填真实选择器，不能填快照整行")
    name: str | None = Field(default=None, max_length=2000)
    frame_selector: str | None = Field(default=None, min_length=1, max_length=2000)


async def locate(*, page: Page, target: Target):
    """构造严格定位器，已知多个匹配时拒绝猜测。

    :returns: 页面或明确 frame 内的 Locator。
    """
    root = page.frame_locator(selector=f"css={target.frame_selector}") if target.frame_selector else page
    if target.by == "role":
        if re.fullmatch(pattern=r"[a-z]+", string=target.value) is None:
            raise BrowserError(code="INVALID_ROLE")
        locator = root.get_by_role(role=target.value, name=target.name, exact=True)
    elif target.by == "label":
        locator = root.get_by_label(text=target.value, exact=True)
    elif target.by == "text":
        locator = root.get_by_text(text=target.value, exact=True)
    elif target.by == "test_id":
        locator = root.get_by_test_id(test_id=target.value)
    else:
        locator = root.locator(selector=f"css={target.value}")
    if await locator.count() > 1:
        raise BrowserError(code="AMBIGUOUS_TARGET")
    return locator


class Capture(BaseModel):
    """保留测试插件的固定 DOM 采集语义。"""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["dom"] = "dom"
    mode: Literal["text", "number", "count", "visible", "url", "attribute", "value"] = "text"
    selector: str | None = Field(default=None, min_length=1, max_length=2000)
    attribute: str | None = Field(default=None, min_length=1, max_length=256)
    field: str | None = Field(default=None, max_length=256)
    index: int | None = Field(default=None, ge=0, le=100000)


CAPTURE_FUNCTION = r"""({captures, origins}) => {
  if (!origins.includes(location.origin)) throw new Error('CAPTURE_OUTSIDE_ORIGIN');
  const values={};
  for (const [name,c] of Object.entries(captures)) {
    if(c.mode==='url'){values[name]=c.field==='pathname'?location.pathname:location.href;continue;}
    const nodes=document.querySelectorAll(c.selector), el=nodes[c.index??0];
    if(c.mode==='count'){values[name]=nodes.length;continue;}
    if(c.mode==='visible'){values[name]=!!el&&!!el.getClientRects().length;continue;}
    if(!el)continue;
    if(c.index===undefined&&nodes.length!==1)throw new Error('AMBIGUOUS_CAPTURE');
    if(c.mode==='value'){values[name]=el.value;continue;}
    let text=(c.attribute?el.getAttribute(c.attribute):el.textContent)?.trim();
    if(c.field==='pathname'&&c.attribute==='href'&&text)text=new URL(text,location.href).pathname;
    if(c.mode==='number'){
      if(text===undefined||text===null||!/^\d+(?:\.\d+)?$/.test(text.replaceAll(',','')))throw new Error('INVALID_CAPTURE_NUMBER');
      values[name]=Number(text.replaceAll(',',''));
    }else if(c.mode==='attribute'){if(text!==null&&text!==undefined)values[name]=text;}
    else values[name]=text;
  }
  return {values,url:location.href,title:document.title,truncated:false};
}"""


class UploadFile(BaseModel):
    """上传显式文件数据，不读取 Hub 任意路径。"""

    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=256, pattern=r"^[^/\\]+$")
    mime_type: str = Field(min_length=1, max_length=128)
    data: str = Field(max_length=6 * 1024 * 1024)


def register_tools(*, tool, browsers, token):
    """在原有 MCP 实例注册替代测试插件依赖的页面能力。"""

    @tool(readonly=True, idempotent=True)
    async def browser_inspect_dom(session_id: Identifier, page_id: Identifier, selector: Annotated[str, Field(min_length=1, max_length=2000)] = "input,textarea,select,button,a,iframe", timeout_ms: Timeout = 10000) -> dict:
        """只读查看 CSS 元素的标签、属性和文本，用于真实定位；不执行调用方脚本。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms) as page:
            value = await page.evaluate(expression="""selector => ({url:location.href,elements:Array.from(document.querySelectorAll(selector)).slice(0,200).map(el=>({tag:el.tagName.toLowerCase(),attributes:Object.fromEntries(Array.from(el.attributes,a=>[a.name,a.value])),text:el.textContent?.trim().slice(0,2000)})),truncated:document.querySelectorAll(selector).length>200})""", arg=selector)
            if len(json.dumps(value, ensure_ascii=False).encode()) > 256 * 1024:
                raise BrowserError(code="DOM_INSPECTION_TOO_LARGE")
            return value

    @tool(readonly=True, idempotent=True)
    async def browser_capture(session_id: Identifier, page_id: Identifier, captures: Annotated[dict[str, Capture], Field(min_length=1, max_length=128)], allowed_origins: Annotated[list[str], Field(min_length=1, max_length=64)], timeout_ms: Timeout = 10000) -> dict:
        """按固定 DOM 合同采集实际值并在同次读取校验来源；不能提交脚本。"""
        for origin in allowed_origins:
            parsed = urlsplit(origin)
            if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
                raise BrowserError(code="INVALID_ALLOWED_ORIGIN")
        definitions = {name: item.model_dump(exclude_none=True) for name, item in captures.items()}
        if any(item.mode != "url" and item.selector is None for item in captures.values()):
            raise BrowserError(code="CAPTURE_SELECTOR_REQUIRED")
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms) as page:
            value = await page.evaluate(expression=CAPTURE_FUNCTION, arg={"captures": definitions, "origins": allowed_origins})
            if len(json.dumps(value, ensure_ascii=False).encode()) > 256 * 1024:
                raise BrowserError(code="CAPTURE_TOO_LARGE")
            return value

    @tool()
    async def browser_press_key(session_id: Identifier, page_id: Identifier, key: Annotated[str, Field(min_length=1, max_length=128)], target: Target | None = None, timeout_ms: Timeout = 10000) -> dict:
        """对当前页面或唯一元素按键；输入与提交分别记录。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            if target:
                await (await locate(page=page, target=target)).press(key=key, timeout=timeout_ms)
            else:
                await page.keyboard.press(key=key)
            return {"completed": True, "url": page.url}

    @tool()
    async def browser_select_option(session_id: Identifier, page_id: Identifier, target: Target, values: Annotated[list[str], Field(min_length=1, max_length=128)], timeout_ms: Timeout = 10000) -> dict:
        """按选项 value 选择下拉框，返回实际选中的 value。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            selected = await (await locate(page=page, target=target)).select_option(value=values, timeout=timeout_ms)
            return {"selected": selected}

    @tool()
    async def browser_check(session_id: Identifier, page_id: Identifier, target: Target, checked: bool, timeout_ms: Timeout = 10000) -> dict:
        """将唯一复选框或单选框设置为明确状态。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            locator = await locate(page=page, target=target)
            await locator.set_checked(checked=checked, timeout=timeout_ms)
            return {"checked": await locator.is_checked(timeout=timeout_ms)}

    @tool()
    async def browser_hover(session_id: Identifier, page_id: Identifier, target: Target, timeout_ms: Timeout = 10000) -> dict:
        """悬停唯一元素，不强制隐藏元素。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            await (await locate(page=page, target=target)).hover(timeout=timeout_ms)
            return {"completed": True}

    @tool()
    async def browser_drag(session_id: Identifier, page_id: Identifier, source: Target, target: Target, timeout_ms: Timeout = 10000) -> dict:
        """将明确源元素拖到明确目标，两边均需唯一。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            await (await locate(page=page, target=source)).drag_to(target=await locate(page=page, target=target), timeout=timeout_ms)
            return {"completed": True}

    @tool()
    async def browser_scroll(session_id: Identifier, page_id: Identifier, delta_x: int = 0, delta_y: int = 600, timeout_ms: Timeout = 10000) -> dict:
        """在本次页面发送滚轮操作，保持当前视口。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            await page.mouse.wheel(delta_x=delta_x, delta_y=delta_y)
            return {"completed": True}

    @tool()
    async def browser_navigate_back(session_id: Identifier, page_id: Identifier, timeout_ms: Timeout = 10000) -> dict:
        """返回浏览历史，等待 DOM 就绪。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            await page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
            return {"url": page.url}

    @tool()
    async def browser_resize(session_id: Identifier, page_id: Identifier, width: Annotated[int, Field(ge=320, le=4096)], height: Annotated[int, Field(ge=200, le=4096)], timeout_ms: Timeout = 10000) -> dict:
        """显式调整本次页面视口，不因截图失败自动缩放。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            await page.set_viewport_size(viewport_size={"width": width, "height": height})
            return {"width": width, "height": height}

    @tool(readonly=True, idempotent=True)
    async def browser_frames(session_id: Identifier, page_id: Identifier, timeout_ms: Timeout = 10000) -> dict:
        """列出本次页面的 frame 名称和地址，操作时显式给出 frame_selector。"""
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms) as page:
            return {"frames": [{"name": frame.name, "url": frame.url} for frame in page.frames]}

    @tool()
    async def browser_tabs(session_id: Identifier, action: Literal["list", "new", "select", "close"] = "list", page_id: Identifier | None = None, timeout_ms: Timeout = 10000) -> dict:
        """列出、创建、选择或关闭本次会话页面；选择返回的 page_id 同时绑定画面。"""
        return await browsers().tabs(session_id=session_id, token=token(), action=action, page_id=page_id, timeout_ms=timeout_ms)

    @tool()
    async def browser_handle_dialog(session_id: Identifier, page_id: Identifier, accept: bool, prompt_text: Annotated[str | None, Field(max_length=20000)] = None) -> dict:
        """设置下一次弹窗策略，须在触发弹窗前调用；无策略时默认 dismiss。"""
        await browsers().set_dialog(session_id=session_id, page_id=page_id, token=token(), accept=accept, prompt_text=prompt_text)
        return {"configured": True, "accept": accept}

    @tool()
    async def browser_file_upload(session_id: Identifier, page_id: Identifier, target: Target, files: Annotated[list[UploadFile], Field(max_length=32)], timeout_ms: Timeout = 10000) -> dict:
        """向唯一文件输入上传显式 base64 数据，最多合计 4 MiB；空列表清空。"""
        payloads = []
        total = 0
        try:
            for item in files:
                buffer = base64.b64decode(item.data, validate=True)
                total += len(buffer)
                if total > UPLOAD_LIMIT:
                    raise BrowserError(code="UPLOAD_TOO_LARGE")
                payloads.append({"name": item.name, "mimeType": item.mime_type, "buffer": buffer})
        except ValueError:
            raise BrowserError(code="INVALID_UPLOAD_DATA") from None
        async with browsers().page(session_id=session_id, page_id=page_id, token=token(), timeout_ms=timeout_ms, mutating=True) as page:
            await (await locate(page=page, target=target)).set_input_files(files=payloads, timeout=timeout_ms)
            return {"files": [item.name for item in files]}
