"""随机凭据验证和本地私有文件。"""

import hashlib
import hmac
import os
import secrets
from pathlib import Path


def token_hash(*, token: str) -> str:
    """计算高熵随机凭据的验证摘要。

    :param token: 凭据原值。
    :returns: SHA-256 摘要。
    """
    return hashlib.sha256(token.encode()).hexdigest()


def matches(*, token: str, expected_hash: str) -> bool:
    """以恒定时间比较验证摘要。

    :param token: 待验证凭据。
    :param expected_hash: 已登记摘要。
    :returns: 是否匹配。
    """
    return hmac.compare_digest(token_hash(token=token), expected_hash)


def bearer_token(*, header: str | None) -> str | None:
    """提取 Bearer 凭据，不接受其他认证方式。

    :param header: Authorization 头。
    :returns: 凭据或空值。
    """
    if header is None:
        return None
    scheme, separator, token = header.partition(" ")
    return token.strip() if separator and scheme.casefold() == "bearer" and token.strip() else None


def generate_token_file(*, path: Path) -> None:
    """生成独立随机凭据文件，拒绝覆盖现有文件。

    :param path: 输出路径。
    """
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as output:
        output.write(f"{secrets.token_urlsafe(48)}\n")
