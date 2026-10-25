"""Hub 的单进程运行配置。"""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class HubSettings(BaseModel):
    """保存设备登记、租约、只读总览与心跳配置，秘密在 repr 中遮蔽。"""

    model_config = ConfigDict(extra="forbid")
    database_path: Path = Path(".runbridge/hub.sqlite3")
    enrollment_token: SecretStr = Field(min_length=32, max_length=256)
    hub_token: SecretStr | None = Field(default=None, min_length=32, max_length=256)
    public_url: str | None = None
    grant_max_lease_seconds: int = Field(default=86400, gt=0, strict=True)
    grant_idle_timeout_seconds: int = Field(default=600, gt=0, strict=True)
    heartbeat_interval_seconds: float = Field(default=30, gt=0)
    heartbeat_timeout_seconds: float = Field(default=90, gt=0)
    web_enabled: bool = True
    web_token: SecretStr | None = Field(default=None, min_length=32, max_length=256)
    mcp_enabled: bool = False
    mcp_allowed_hosts: list[str] = Field(default_factory=list)
    mcp_allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeout(self):
        """心跳超时必须长于发送间隔。

        :returns: 当前配置。
        """
        if self.heartbeat_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("心跳超时必须长于发送间隔")
        if self.web_token is not None and self.web_token == self.enrollment_token:
            raise ValueError("总览只读口令必须与登记凭据不同")
        if self.hub_token is not None and self.hub_token in {self.enrollment_token, self.web_token}:
            raise ValueError("Hub 申请凭据必须与登记及总览凭据不同")
        if self.public_url is not None:
            parts = urlsplit(self.public_url)
            if parts.scheme not in {"http", "https"} or not parts.hostname or parts.username or parts.password or parts.query or parts.fragment:
                raise ValueError("public_url 必须是无凭据、查询及片段的 HTTP(S) 基址")
            self.public_url = self.public_url.rstrip("/")
        if self.mcp_enabled:
            if "*" in self.mcp_allowed_hosts or "*" in self.mcp_allowed_origins:
                raise ValueError("MCP Host 和 Origin 列表不支持全局通配符；Host 留空表示不限制")
        return self
