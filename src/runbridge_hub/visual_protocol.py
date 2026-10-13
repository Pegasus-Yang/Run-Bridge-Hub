"""独立画面合同与 HTTP 查询扩展，不进入控制消息或持久化记录。"""

from typing import Annotated, Literal

from packaging.specifiers import SpecifierSet
from packaging.version import InvalidVersion
from pydantic import AwareDatetime, Field, SecretStr, TypeAdapter, field_validator

from runbridge_hub.protocol import Identifier, Model, NodeView, SessionView


VISUAL_PROTOCOL = "runbridge-visual-v1"
BROWSCREEN_VERSION_RANGE = ">=0.3.1,<0.4.0"
BROWSCREEN_VERSIONS = SpecifierSet(BROWSCREEN_VERSION_RANGE)
VisualState = Literal["UNAVAILABLE", "WAITING", "WAITING_TARGET", "LIVE", "STALE", "ERROR", "STOPPED"]


def supported_browscreen_version(*, value: str | None) -> bool:
    """按安装依赖相同的规则检查正式版本。

    :param value: 已安装或上传握手声明的分发版本。
    :returns: 版本是否合法、非预发布且位于支持范围内。
    """
    if value is None:
        return False
    try:
        return BROWSCREEN_VERSIONS.contains(item=value, prereleases=False)
    except InvalidVersion:
        return False


class VisualTarget(Model):
    """已授权实例内的页面标识，不包含地址或真实标题。"""

    target_id: Identifier
    label: str = Field(min_length=1, max_length=64)


class VisualSelection(Model):
    """最近一次目标切换的实际进度。"""

    request_id: Identifier
    target_id: Identifier
    state: Literal["PENDING", "APPLIED", "FAILED"] = "PENDING"
    error_code: Identifier | None = None


class VisualView(Model):
    """单个会话的临时画面视图。"""

    supported: bool = False
    state: VisualState = "UNAVAILABLE"
    visual_protocol_version: Literal[1] = 1
    transport: Literal["websocket"] = "websocket"
    content_type: Literal["image/png"] = "image/png"
    stream_path: str | None = None
    target_id: Identifier | None = None
    targets: list[VisualTarget] = Field(default_factory=list, max_length=256)
    stream_id: Identifier | None = None
    last_frame_id: int | None = None
    capture_started_at: AwareDatetime | None = None
    frame_age_ms: int | None = None
    reason_code: Identifier | None = None
    selection: VisualSelection | None = None


class VisualStreamView(VisualView):
    """节点查询中属于当前许可的活动画面。"""

    session_id: Identifier
    resource_id: Identifier


class NodeVisualView(Model):
    """声明能力与活动数据流分开返回。"""

    supported: bool = False
    streams: list[VisualStreamView] = Field(default_factory=list, max_length=256)


class NodeQueryView(NodeView):
    """查询扩展可缺省，从而允许新客户端查询旧 Hub。"""

    visual: NodeVisualView | None = None


class SessionQueryView(SessionView):
    """会话查询附带内存画面信息，基础会话模型保持原样。"""

    visual: VisualView | None = None


class VisualFrame(Model):
    """和 PNG 整体传输的来源元数据。"""

    visual_protocol_version: Literal[1] = 1
    connection_generation: int = Field(ge=1)
    session_id: Identifier
    resource_id: Identifier
    stream_id: Identifier
    target_id: Identifier
    frame_id: int = Field(ge=1)
    capture_started_at: AwareDatetime
    content_type: Literal["image/png"] = "image/png"


class VisualHello(Model):
    """上传连接的版本握手。"""

    type: Literal["hello"] = "hello"
    visual_protocol_version: Literal[1] = 1
    browscreen_version: str = "0.3.1"

    @field_validator("browscreen_version")
    @classmethod
    def validate_browscreen_version(cls, value: str) -> str:
        """接受范围内版本，不能将任意版本降格为协议 v1。

        :returns: 实际上报且受支持的版本。
        """
        if not supported_browscreen_version(value=value):
            raise ValueError(f"Browscreen 版本必须满足 {BROWSCREEN_VERSION_RANGE}，不接受预发布版")
        return value


class VisualTargets(Model):
    """目标目录更新不改变当前帧状态。"""

    type: Literal["targets"] = "targets"
    targets: list[VisualTarget] = Field(max_length=256)


class VisualSourceState(Model):
    """采集端只声明等待或错误，LIVE 由 Hub 收到图片确认。"""

    type: Literal["state"] = "state"
    state: Literal["WAITING", "WAITING_TARGET", "ERROR"]
    stream_id: Identifier | None = None
    target_id: Identifier | None = None
    reason_code: Identifier | None = None
    request_id: Identifier | None = None


class VisualTargetRequest(Model):
    """只能提交目标 ID，不能提交调试端点。"""

    target_id: Identifier


class VisualSelect(VisualTargetRequest):
    """Hub 在独立上传连接上转发画面源选择。"""

    type: Literal["select_target"] = "select_target"
    request_id: Identifier


class VisualAuth(Model):
    """浏览器订阅者的首条认证消息。"""

    type: Literal["auth"] = "auth"
    access_token: SecretStr = Field(min_length=1, max_length=256)


VisualIncoming = Annotated[VisualHello | VisualTargets | VisualSourceState, Field(discriminator="type")]
VisualIncomingAdapter = TypeAdapter(VisualIncoming)
