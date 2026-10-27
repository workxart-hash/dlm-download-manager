"""Chrome native-messaging wire framing.

Each message is a 4-byte length (native byte order) followed by that many bytes
of UTF-8 JSON. ``read_message`` returns ``None`` at a clean end-of-stream and
raises ``EOFError`` on a truncated frame.
"""

from __future__ import annotations

import json
import struct
from typing import BinaryIO, Optional

_LEN = struct.Struct("=I")  # native byte order, as Chrome requires
MAX_MESSAGE = 64 * 1024 * 1024  # defensive cap on an inbound frame


def _read_exactly(stream: BinaryIO, n: int) -> Optional[bytes]:
    chunks = []
    remaining = n
    while remaining:
        chunk = stream.read(remaining)
        if not chunk:
            return None if len(chunks) == 0 and remaining == n else b"".join(chunks)
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def read_message(stream: BinaryIO) -> Optional[dict]:
    header = _read_exactly(stream, 4)
    if header is None:
        return None            # clean EOF between messages
    if len(header) < 4:
        raise EOFError("truncated length prefix")
    (length,) = _LEN.unpack(header)
    if length > MAX_MESSAGE:
        raise ValueError(f"message too large: {length} bytes")
    body = _read_exactly(stream, length) if length else b""
    if body is None or len(body) < length:
        raise EOFError("truncated message body")
    return json.loads(body.decode("utf-8"))


def write_message(stream: BinaryIO, obj: dict) -> None:
    data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
    stream.write(_LEN.pack(len(data)))
    stream.write(data)
    stream.flush()
