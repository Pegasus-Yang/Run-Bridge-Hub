"""Hub 的持久启动设置与运行配置转换。"""

import os
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field

from runbridge_hub.settings import HubSettings


class ServeSettings(BaseModel):
    """保存启动参数；登记秘密只从文件或环境读取。"""

    model_config = ConfigDict(extra="forbid")

    config_version: Literal[1] = 1
    host: str = "127.0.0.1"
    port: int = Field(default=8787, ge=0, le=65535)
    database_path: Path = Path(".runbridge/hub.sqlite3")
    enrollment_token_file: Path | None = None
    web_enabled: bool = True
    web_token_file: Path | None = None
    heartbeat_interval_seconds: float = 30
    heartbeat_timeout_seconds: float = 90
    mcp_enabled: bool = False
    mcp_allowed_hosts: list[str] = Field(default_factory=list)
    mcp_allowed_origins: list[str] = Field(default_factory=list)

    @classmethod
    def load(cls, *, path: Path):
        """读取 YAML，将本地相对路径锚定到配置所在目录。

        :param path: UTF-8 YAML 文件。
        :returns: 已验证的启动设置。
        """
        try:
            values = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            raise ValueError("YAML 格式无效，输入内容已隐藏") from None
        if not isinstance(values, dict):
            raise ValueError("YAML 顶层必须是配置对象")
        base = path.resolve().parent
        for key, default in (
            ("database_path", ".runbridge/hub.sqlite3"),
            ("enrollment_token_file", None),
            ("web_token_file", None),
        ):
            value = values.get(key, default)
            if isinstance(value, str):
                values[key] = (base / value).resolve()
        return cls.model_validate(values)

    def hub_settings(self) -> HubSettings:
        """读取登记秘密，复用 Hub 的心跳与 MCP 约束。

        :returns: 可用于创建应用的配置。
        """
        token = (
            self.enrollment_token_file.read_text(encoding="utf-8").strip()
            if self.enrollment_token_file is not None
            else os.environ.get("RUNBRIDGE_ENROLLMENT_TOKEN")
        )
        if not token:
            raise ValueError(
                "请提供 enrollment_token_file、--enrollment-token-file 或 RUNBRIDGE_ENROLLMENT_TOKEN"
            )
        web_token = None
        if self.web_enabled:
            web_token = (
                self.web_token_file.read_text(encoding="utf-8").strip()
                if self.web_token_file is not None
                else os.environ.get("RUNBRIDGE_WEB_TOKEN")
            )
            if web_token == "":
                raise ValueError("总览只读口令文件或 RUNBRIDGE_WEB_TOKEN 不能为空")
        values = HubSettings(
            database_path=self.database_path,
            enrollment_token=token,
            web_enabled=self.web_enabled,
            web_token=web_token,
            heartbeat_interval_seconds=self.heartbeat_interval_seconds,
            heartbeat_timeout_seconds=self.heartbeat_timeout_seconds,
            mcp_enabled=self.mcp_enabled,
            mcp_allowed_origins=self.mcp_allowed_origins,
        ).model_dump()
        values["mcp_allowed_hosts"].extend(self.mcp_allowed_hosts)
        return HubSettings.model_validate(values)
