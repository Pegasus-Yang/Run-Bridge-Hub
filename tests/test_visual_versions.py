"""画面握手与安装依赖使用一致的版本范围。"""

import pytest
from pydantic import ValidationError

from runbridge_hub.visual_protocol import VisualHello


@pytest.mark.parametrize("value", ["0.3.1", "0.3.2", "0.3.10", "0.3.1.post1", "0.3.2+local"])
def test_hello_accepts_compatible_release(value):
    """接受后续补丁、正式修订和本地构建，保留实际上报版本。"""
    assert VisualHello(browscreen_version=value).browscreen_version == value


@pytest.mark.parametrize("value", [None, "", "0.3.0", "0.3.2rc1", "0.4.0.dev1", "0.4.0", "0.4.1", "invalid"])
def test_hello_rejects_missing_or_unsupported_version(value):
    """明确声明的无效版本不能被默认版本替换。"""
    with pytest.raises(ValidationError):
        VisualHello(browscreen_version=value)
