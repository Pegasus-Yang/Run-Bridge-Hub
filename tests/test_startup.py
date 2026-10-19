"""Hub YAML 的路径、CLI 兼容与无效配置阻断。"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from runbridge_hub.cli import main
from runbridge_hub.startup import ServeSettings


def test_yaml_startup_from_other_directory_uses_file_paths_and_token(
    tmp_path, monkeypatch
):
    directory = tmp_path / "office"
    directory.mkdir()
    token = "file-secret-" + "x" * 48
    (directory / "enrollment.token").write_text(token + "\n", encoding="utf-8")
    path = directory / "hub.yaml"
    path.write_text(
        """config_version: 1
host: 0.0.0.0
port: 9000
enrollment_token_file: enrollment.token
heartbeat_interval_seconds: 10
heartbeat_timeout_seconds: 40
mcp_enabled: true
mcp_allowed_hosts: [hub.example:9000]
mcp_allowed_origins: [https://console.example]
""",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("RUNBRIDGE_ENROLLMENT_TOKEN", "env-secret-" + "y" * 48)
    create = Mock(return_value=object())
    run = Mock()
    monkeypatch.setattr("runbridge_hub.cli.create_app", create)
    monkeypatch.setattr("runbridge_hub.cli.uvicorn.run", run)
    monkeypatch.setattr("sys.argv", ["runbridge-hub", "serve", "--settings", str(path)])
    main()
    settings = create.call_args.kwargs["settings"]
    assert settings.enrollment_token.get_secret_value() == token
    assert settings.database_path == directory / ".runbridge/hub.sqlite3"
    assert settings.heartbeat_interval_seconds == 10
    assert settings.heartbeat_timeout_seconds == 40
    assert "localhost:*" in settings.mcp_allowed_hosts
    assert "hub.example:9000" in settings.mcp_allowed_hosts
    assert settings.mcp_allowed_origins == ["https://console.example"]
    assert settings.mcp_enabled is True
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["port"] == 9000
    assert run.call_args.kwargs["workers"] == 1
    assert not settings.database_path.exists()


def test_cli_retains_defaults_and_repeated_hosts(monkeypatch):
    monkeypatch.setenv("RUNBRIDGE_ENROLLMENT_TOKEN", "x" * 64)
    create = Mock()
    run = Mock()
    monkeypatch.setattr("runbridge_hub.cli.create_app", create)
    monkeypatch.setattr("runbridge_hub.cli.uvicorn.run", run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "runbridge-hub",
            "serve",
            "--enable-mcp",
            "--mcp-allowed-host",
            "hub.test:8787",
            "--mcp-allowed-host",
            "hub.local:*",
        ],
    )
    main()
    settings = create.call_args.kwargs["settings"]
    assert settings.database_path == Path(".runbridge/hub.sqlite3")
    assert settings.mcp_allowed_hosts[-2:] == ["hub.test:8787", "hub.local:*"]
    assert settings.heartbeat_interval_seconds == 30
    assert settings.heartbeat_timeout_seconds == 90
    assert run.call_args.kwargs["host"] == "127.0.0.1"
    assert run.call_args.kwargs["port"] == 8787


@pytest.mark.parametrize(
    "text",
    [
        "- not-a-mapping",
        "enrollment_token_file: [",
        "unknown_setting: true",
        "config_version: 2",
        "port: 65536",
        "mcp_enabled: true\nmcp_allowed_hosts: ['*']",
        "heartbeat_interval_seconds: 90\nheartbeat_timeout_seconds: 30",
    ],
)
def test_invalid_yaml_does_not_start_or_create_database(
    tmp_path, monkeypatch, capsys, text
):
    path = tmp_path / "hub.yaml"
    path.write_text(text, encoding="utf-8")
    monkeypatch.setenv("RUNBRIDGE_ENROLLMENT_TOKEN", "x" * 64)
    monkeypatch.setattr("sys.argv", ["runbridge-hub", "serve", "--settings", str(path)])
    create = Mock()
    monkeypatch.setattr("runbridge_hub.cli.create_app", create)
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    create.assert_not_called()
    assert "Traceback" not in capsys.readouterr().err
    assert not (tmp_path / ".runbridge").exists()


def test_yaml_and_cli_cannot_be_mixed(monkeypatch, capsys):
    monkeypatch.setattr(
        "sys.argv",
        ["runbridge-hub", "serve", "--settings", "hub.yaml", "--port", "8787"],
    )
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    assert "不能混用" in capsys.readouterr().err


def test_secret_values_are_hidden_when_validation_fails(tmp_path, monkeypatch, capsys):
    secret = "invalid-secret"
    path = tmp_path / "hub.yaml"
    path.write_text("enrollment_token_file: enrollment.token\n", encoding="utf-8")
    (tmp_path / "enrollment.token").write_text(secret, encoding="utf-8")
    monkeypatch.setattr("sys.argv", ["runbridge-hub", "serve", "--settings", str(path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert secret not in output.out + output.err
    assert "enrollment_token" in output.err


def test_missing_selected_token_file_does_not_fall_back_to_environment(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("RUNBRIDGE_ENROLLMENT_TOKEN", "x" * 64)
    settings = ServeSettings(enrollment_token_file=tmp_path / "missing.token")
    with pytest.raises(FileNotFoundError):
        settings.hub_settings()


def test_explicit_database_path_is_anchored_to_yaml(tmp_path):
    path = tmp_path / "hub.yaml"
    path.write_text("database_path: data/hub.sqlite3\n", encoding="utf-8")
    assert ServeSettings.load(path=path).database_path == tmp_path / "data/hub.sqlite3"


@pytest.mark.parametrize("port", [9000, 0])
def test_legacy_cli_file_and_custom_parameters_are_preserved(
    tmp_path, monkeypatch, port
):
    token_file = tmp_path / "enrollment.token"
    token_file.write_text("x" * 64, encoding="utf-8")
    create = Mock()
    run = Mock()
    monkeypatch.setattr("runbridge_hub.cli.create_app", create)
    monkeypatch.setattr("runbridge_hub.cli.uvicorn.run", run)
    monkeypatch.setattr(
        "sys.argv",
        [
            "runbridge-hub",
            "serve",
            "--enrollment-token-file",
            str(token_file),
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
            "--db-path",
            "other.sqlite3",
            "--heartbeat-interval",
            "10",
            "--heartbeat-timeout",
            "40",
        ],
    )
    main()
    settings = create.call_args.kwargs["settings"]
    assert settings.database_path == Path("other.sqlite3")
    assert settings.enrollment_token.get_secret_value() == "x" * 64
    assert settings.heartbeat_interval_seconds == 10
    assert settings.heartbeat_timeout_seconds == 40
    assert settings.mcp_enabled is False
    assert run.call_args.kwargs["host"] == "0.0.0.0"
    assert run.call_args.kwargs["port"] == port
