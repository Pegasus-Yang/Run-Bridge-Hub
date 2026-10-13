"""Hub 的单进程运行配置。"""

from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class HubSettings(BaseModel):
    """保存登记秘密和心跳配置，秘密在 repr 中遮蔽。"""

    model_config = ConfigDict(extra="forbid")
    database_path: Path = Path(".runbridge/hub.sqlite3")
    enrollment_token: SecretStr = Field(min_length=32, max_length=256)
    heartbeat_interval_seconds: float = Field(default=30, gt=0)
    heartbeat_timeout_seconds: float = Field(default=90, gt=0)
    mcp_enabled: bool = False
    mcp_native_url: str | None = None
    mcp_allowed_hosts: list[str] = Field(default_factory=lambda: ["127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*"])
    mcp_allowed_origins: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_timeout(self):
        """心跳超时必须长于发送间隔。

        :returns: 当前配置。
        """
        if self.heartbeat_timeout_seconds <= self.heartbeat_interval_seconds:
            raise ValueError("心跳超时必须长于发送间隔")
        if self.mcp_enabled:
            address = urlsplit(self.mcp_native_url or "")
            if address.scheme not in {"http", "https"} or not address.hostname or address.username or address.password or address.query or address.fragment or address.path not in {"", "/"}:
                raise ValueError("MCP 需要指向当前 Hub 的 HTTP(S) 根地址")
            if not self.mcp_allowed_hosts or "*" in self.mcp_allowed_hosts or "*" in self.mcp_allowed_origins:
                raise ValueError("MCP Host 和 Origin 必须显式允许，不能使用全局通配符")
        return self
