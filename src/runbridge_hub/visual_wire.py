"""有界二进制画面封包，图片与元数据在同一消息内。"""

import struct

from pydantic import ValidationError

from runbridge_hub.visual_protocol import VisualFrame


HEADER_MAX_BYTES = 4096
PNG_MAX_BYTES = 4 * 1024 * 1024
VISUAL_MAX_BYTES = 4 + HEADER_MAX_BYTES + PNG_MAX_BYTES
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
STATE_MAX_BYTES = 65_536


def pack_frame(*, metadata: VisualFrame, png: bytes) -> bytes:
    """校验帧并整体编码。

    :raises ValueError: 图片或元数据大小不符合合同。
    """
    header = metadata.model_dump_json().encode(encoding="utf-8")
    if len(header) > HEADER_MAX_BYTES or len(png) > PNG_MAX_BYTES or not png.startswith(PNG_SIGNATURE):
        raise ValueError("画面大小或 PNG 标识无效")
    return struct.pack("!I", len(header)) + header + png


def unpack_frame(*, data: bytes) -> tuple[VisualFrame, bytes]:
    """在限定大小内解析帧，不在 Hub 解码图像。

    :raises ValueError: 数据不是完整的合同帧。
    """
    if len(data) < 4 or len(data) > VISUAL_MAX_BYTES:
        raise ValueError("画面消息大小无效")
    length = struct.unpack("!I", data[:4])[0]
    if not 0 < length <= HEADER_MAX_BYTES or 4 + length >= len(data):
        raise ValueError("画面头长度无效")
    png = data[4 + length:]
    if len(png) > PNG_MAX_BYTES or not png.startswith(PNG_SIGNATURE):
        raise ValueError("画面 PNG 无效")
    try:
        metadata = VisualFrame.model_validate_json(data[4:4 + length])
    except ValidationError:
        raise ValueError("画面元数据无效") from None
    return metadata, png
