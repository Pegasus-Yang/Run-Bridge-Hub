"""独立订阅已激活的会话，解包并保存有限数量的 PNG。"""

import argparse
import asyncio
import json
import struct
import sys
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import httpx
from websockets.asyncio.client import connect
from websockets.exceptions import WebSocketException


MAX_HEADER = 4096
MAX_PNG = 4 * 1024 * 1024
MAX_MESSAGE = 4 + MAX_HEADER + MAX_PNG
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def unpack_frame(*, data: bytes) -> tuple[dict, bytes]:
    """按公开封包合同拆分元数据与 PNG。

    :raises ValueError: 长度、格式或 PNG 签名不符合合同。
    :returns: 元数据及图片字节；图片完整解码交给实际消费者。
    """
    if not 4 < len(data) <= MAX_MESSAGE:
        raise ValueError("画面消息长度无效")
    length = struct.unpack_from(">I", data)[0]
    if not 0 < length <= MAX_HEADER or 4 + length >= len(data):
        raise ValueError("元数据长度无效")
    metadata = json.loads(data[4 : 4 + length].decode(encoding="utf-8"))
    png = data[4 + length :]
    if (
        not isinstance(metadata, dict)
        or metadata.get("visual_protocol_version") != 1
        or metadata.get("content_type") != "image/png"
    ):
        raise ValueError("画面合同不匹配")
    if len(png) > MAX_PNG or not png.startswith(PNG_SIGNATURE):
        raise ValueError("PNG 格式无效")
    return metadata, png


async def execute(*, args) -> None:
    """保持单个接收循环，不创建执行会话或改变业务页面。

    :param args: 调用许可、已激活会话 ID、帧数与可选目标 ID。
    """
    access = json.loads(args.access_file.read_text(encoding="utf-8"))
    hub = access["hub_url"].rstrip("/")
    headers = {"Authorization": f"Bearer {access['access_token']}"}
    async with httpx.AsyncClient(timeout=15) as client:
        session_url = f"{hub}/v2/sessions/{args.session_id}"
        response = await client.get(url=session_url, headers=headers)
        response.raise_for_status()
        session = response.json()
        visual = session.get("visual")
        if not visual or not visual.get("stream_path"):
            raise ValueError("会话尚未 ACTIVE 或画面不可用")
        address = urlsplit(hub)
        uri = urlunsplit(
            (
                "wss" if address.scheme == "https" else "ws",
                address.netloc,
                address.path + visual["stream_path"],
                "",
                "",
            )
        )
        if args.list_targets:
            print(
                json.dumps(
                    {
                        "state": visual["state"],
                        "targets": visual["targets"],
                        "stream_path": visual["stream_path"],
                    },
                    ensure_ascii=False,
                )
            )
            return
        if args.target_id:
            if args.target_id not in {
                target["target_id"] for target in visual["targets"]
            }:
                raise ValueError("目标不在本次查询返回的列表中，请稍后重新查询")
            selected = await client.put(
                url=f"{hub}/v1/sessions/{args.session_id}/visual/target",
                headers=headers,
                json={"target_id": args.target_id},
            )
            selected.raise_for_status()
            print(
                json.dumps({"selection": selected.json()}, ensure_ascii=False),
                flush=True,
            )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        written = 0
        latest_key = None
        last_frame = 0
        last_state = None
        async with (
            asyncio.timeout(delay=args.timeout),
            connect(
                uri=uri, additional_headers=headers, max_size=MAX_MESSAGE, max_queue=1
            ) as stream,
        ):
            while written < args.frame_count:
                message = await stream.recv()
                if isinstance(message, str):
                    event = json.loads(message)
                    if event.get("type") != "state":
                        raise ValueError("未知的画面文本消息")
                    visual = event["visual"]
                    summary = {
                        key: visual.get(key)
                        for key in (
                            "state",
                            "reason_code",
                            "target_id",
                            "targets",
                            "selection",
                        )
                    }
                    if summary != last_state:
                        print(json.dumps(summary, ensure_ascii=False), flush=True)
                        last_state = summary
                    continue
                metadata, png = unpack_frame(data=message)
                if (
                    metadata.get("session_id") != args.session_id
                    or metadata.get("connection_generation")
                    != session["connection_generation"]
                ):
                    raise ValueError("画面不属于当前会话代次")
                if visual["state"] != "LIVE" or (
                    metadata.get("stream_id"),
                    metadata.get("target_id"),
                ) != (visual["stream_id"], visual["target_id"]):
                    continue
                if args.target_id and metadata["target_id"] != args.target_id:
                    continue
                key = metadata["stream_id"]
                if key != latest_key:
                    latest_key, last_frame = key, 0
                number = metadata.get("frame_id")
                if (
                    not isinstance(number, int)
                    or isinstance(number, bool)
                    or number <= last_frame
                ):
                    raise ValueError("画面帧号无效或倒退")
                last_frame = number
                written += 1
                output = args.output_dir / f"frame-{written:03d}.png"
                output.write_bytes(png)
                print(
                    json.dumps(
                        {
                            "file": str(output),
                            "frame_id": number,
                            "png_bytes": len(png),
                        },
                        ensure_ascii=False,
                    ),
                    flush=True,
                )


def main() -> None:
    """读取少量帧后关闭订阅，工具执行会话由其调用方管理。"""
    parser = argparse.ArgumentParser(description="RunBridge 画面流订阅示例")
    parser.add_argument("--access-file", type=Path, required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--target-id")
    parser.add_argument("--list-targets", action="store_true")
    parser.add_argument("--frame-count", type=int, default=3)
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument(
        "--output-dir", type=Path, default=Path(".runbridge/visual-frames")
    )
    args = parser.parse_args()
    if args.frame_count < 1 or args.timeout <= 0:
        parser.error("帧数和超时必须大于 0")
    try:
        asyncio.run(execute(args=args))
    except (
        httpx.HTTPError,
        WebSocketException,
        TimeoutError,
        OSError,
        ValueError,
        KeyError,
        KeyboardInterrupt,
    ):
        print(
            "订阅结束或失败；请查询画面状态、目标与许可，执行会话仍由原调用方管理",
            file=sys.stderr,
        )
        raise SystemExit(1) from None


if __name__ == "__main__":
    main()
