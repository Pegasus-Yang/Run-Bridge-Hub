"""RunBridge v2 工具会话合同；登记和访问凭据仍沿用 v1。"""

from typing import Annotated, Literal

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, SecretStr, TypeAdapter, model_validator


Identifier = Annotated[str, Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]*$")]


class Model(BaseModel):
    """拒绝本服务控制字段中的拼写或版本错误。"""

    model_config = ConfigDict(extra="forbid")


class BackendCapability(Model):
    """工具安装元数据与实际能力覆盖分开表示。"""

    name: Identifier
    installed: bool | None = None
    runtime_version: str | None = None
    version_status: Literal["NOT_PROBED", "NOT_INSTALLED", "DETECTED"] = "NOT_PROBED"
    declared_protocols: list[str] = Field(default_factory=list, max_length=16)
    coverage_status: Literal["NOT_IMPLEMENTED", "REQUIRES_VERIFICATION", "SUPPORTED"] = "NOT_IMPLEMENTED"


class ResourceCapability(Model):
    """资源目录条目，不以安装信息推断资源就绪。"""

    resource_id: Identifier
    backend: Identifier
    kind: str = Field(min_length=1, max_length=64)
    readiness: Literal["NEEDS_PROBE", "NEEDS_AUTHORIZATION", "READY", "UNAVAILABLE"] = "NEEDS_PROBE"
    occupancy: Literal["FREE", "BUSY", "UNKNOWN"] = "UNKNOWN"
    authorization_scope: Literal["BROWSER_INSTANCE"] | None = None
    tool: Identifier = "playwright"
    tool_api_version: int = 1
    methods: list[str] = Field(default_factory=list, max_length=256)


class CapabilitySnapshot(Model):
    """节点报告的本机能力快照。"""

    host: dict[str, str] = Field(default_factory=dict)
    backends: list[BackendCapability] = Field(default_factory=list, max_length=64)
    resources: list[ResourceCapability] = Field(default_factory=list, max_length=256)

    @model_validator(mode="after")
    def unique_entries(self):
        """确保资源和后端名称没有重复。

        :returns: 当前快照。
        """
        if len({item.name for item in self.backends}) != len(self.backends):
            raise ValueError("后端名称重复")
        if len({item.resource_id for item in self.resources}) != len(self.resources):
            raise ValueError("资源 ID 重复")
        return self


class Registration(Model):
    """节点首次登记或同一身份的幂等重试。"""

    node_id: Identifier
    name: str = Field(min_length=1, max_length=128)
    node_token: SecretStr = Field(min_length=32, max_length=256)


class RegistrationResult(Model):
    """登记结果不回显节点秘密。"""

    protocol_version: Literal[1] = 1
    node_id: Identifier
    created: bool


class GrantRequest(Model):
    """节点所有者创建对接许可。"""

    resource_ids: list[Identifier] | None = None
    expires_in_seconds: float | None = Field(default=None, gt=0, le=31_536_000)


class GrantView(Model):
    """许可查询不包含凭据原值。"""

    grant_id: Identifier
    node_id: Identifier
    resource_ids: list[Identifier] | None
    created_at: AwareDatetime
    expires_at: AwareDatetime | None
    revoked_at: AwareDatetime | None


class GrantCreated(GrantView):
    """新凭据只在创建时交付一次。"""

    access_token: str


class NodeView(Model):
    """节点当前连接与能力快照的查询结果。"""

    protocol_version: Literal[1] = 1
    node_id: Identifier
    name: str
    connection_status: Literal["OFFLINE", "PREPARING", "ONLINE"]
    connection_generation: int
    heartbeat_count: int
    last_seen_at: AwareDatetime | None
    capabilities_observed_at: AwareDatetime | None
    observation_age_ms: int | None
    capabilities_stale: bool
    capabilities: CapabilitySnapshot | None


class SessionCreate(Model):
    """申请工具资源，不要求调用方安装执行库。"""

    resource_id: Identifier
    tool: Identifier = "playwright"
    request_id: Identifier | None = None
    lease_seconds: float = Field(default=300, ge=1, le=3600)


class SessionView(Model):
    """会话元数据，不保存原生协议帧、启动秘密或本机端点。"""

    protocol_version: Literal[1, 2] = 2
    session_id: Identifier
    node_id: Identifier
    resource_id: Identifier
    grant_id: Identifier
    connection_generation: int
    backend: str = "playwright"
    runtime_version: str
    tool: Identifier = "playwright"
    tool_api_version: int = 1
    request_id: Identifier | None = None
    objects: dict = Field(default_factory=dict)
    authorization_scope: Literal["BROWSER_INSTANCE"] | None = None
    state: Literal["PREPARING", "READY", "ACTIVE", "CLOSING", "CLOSED", "FAILED", "INTERRUPTED"]
    cleanup: Literal["PENDING", "COMPLETE", "UNKNOWN"] = "PENDING"
    execution_outcome: Literal["NOT_STARTED", "NOT_TRACKED", "OUTCOME_UNKNOWN"] = "NOT_STARTED"
    created_at: AwareDatetime
    updated_at: AwareDatetime
    expires_at: AwareDatetime
    close_reason: str | None = None
    error_code: str | None = None

    @classmethod
    def from_record(cls, record: dict):
        """历史记录保持旧协议标记，读取时仅投影公开字段。"""
        return cls.model_validate({key: value for key, value in record.items() if key in cls.model_fields})


class Message(Model):
    """所有控制消息携带合同版本。"""

    protocol_version: Literal[2] = 2


class Welcome(Message):
    type: Literal["welcome"] = "welcome"
    node_id: Identifier
    connection_generation: int = Field(ge=1)
    heartbeat_interval_seconds: float = Field(gt=0)
    heartbeat_timeout_seconds: float = Field(gt=0)


class Heartbeat(Message):
    type: Literal["heartbeat"] = "heartbeat"
    connection_generation: int = Field(ge=1)


class CapabilityReport(Message):
    type: Literal["capabilities"] = "capabilities"
    connection_generation: int = Field(ge=1)
    capabilities: CapabilitySnapshot


class Acknowledgement(Message):
    type: Literal["heartbeat_ack", "capabilities_ack"]
    connection_generation: int = Field(ge=1)
    observed_at: AwareDatetime
    heartbeat_count: int


class ControlError(Message):
    type: Literal["error"] = "error"
    code: str


class SessionOpen(Message):
    type: Literal["session_open"] = "session_open"
    connection_generation: int
    session_id: Identifier
    resource_id: Identifier
    tool: Identifier = "playwright"
    tool_api_version: int = 1


class SessionStop(Message):
    type: Literal["session_stop"] = "session_stop"
    connection_generation: int
    session_id: Identifier
    reason: str


class SessionPrepared(Message):
    type: Literal["session_prepared"] = "session_prepared"
    connection_generation: int
    session_id: Identifier
    runtime_version: str | None = None
    objects: dict = Field(default_factory=dict)
    error_code: str | None = None


class SessionClosed(Message):
    type: Literal["session_closed"] = "session_closed"
    connection_generation: int
    session_id: Identifier
    cleanup: Literal["COMPLETE", "UNKNOWN"]
    error_code: str | None = None


class SessionAcknowledgement(Message):
    type: Literal["session_ack"] = "session_ack"
    connection_generation: int
    session_id: Identifier


IncomingMessage = Annotated[Heartbeat | CapabilityReport | SessionPrepared | SessionClosed, Field(discriminator="type")]
IncomingAdapter = TypeAdapter(IncomingMessage)
OutgoingMessage = Annotated[Acknowledgement | SessionAcknowledgement | SessionOpen | SessionStop | ControlError, Field(discriminator="type")]
OutgoingAdapter = TypeAdapter(OutgoingMessage)
