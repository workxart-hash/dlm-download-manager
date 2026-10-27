"""The native-messaging host process.

Chrome launches this, sends JSON messages on stdin and reads JSON on stdout
(both framed by :mod:`dlm.native.protocol`). A ``download`` message hands the
URL off to a detached ``dlm get`` process so the host can answer immediately.

Nothing may be written to stdout except framed responses, or the channel
breaks — diagnostics go to stderr only.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import BinaryIO, Callable, Optional

from .. import __version__
from .protocol import read_message, write_message

Launcher = Callable[[str, Optional[str], dict], None]


def _resolve_output(filename: Optional[str]) -> Optional[str]:
    if not filename:
        return None
    p = Path(filename)
    if p.is_absolute():
        return str(p)
    # Chrome often supplies just a basename: drop it into the Downloads folder.
    return str(Path.home() / "Downloads" / p.name)


def default_launcher(url: str, filename: Optional[str], options: dict) -> None:
    cmd = [sys.executable, "-m", "dlm", "get", url]
    out = _resolve_output(filename)
    if out:
        cmd += ["-o", out]
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
            subprocess, "CREATE_NO_WINDOW", 0
        )
    subprocess.Popen(
        cmd,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=flags,
        close_fds=True,
    )


def handle_message(msg: dict, launcher: Launcher = default_launcher) -> dict:
    mtype = msg.get("type")
    if mtype == "ping":
        return {"ok": True, "pong": True, "version": __version__}
    if mtype == "download":
        url = msg.get("url")
        if not url:
            return {"ok": False, "error": "missing url"}
        try:
            launcher(url, msg.get("filename"), msg)
        except Exception as e:  # noqa: BLE001 - report back to the extension
            return {"ok": False, "error": f"{type(e).__name__}: {e}"}
        return {"ok": True, "queued": url}
    return {"ok": False, "error": f"unknown message type {mtype!r}"}


def serve(stdin: BinaryIO, stdout: BinaryIO, launcher: Launcher = default_launcher) -> None:
    while True:
        msg = read_message(stdin)
        if msg is None:
            return
        write_message(stdout, handle_message(msg, launcher))


def main() -> int:
    try:
        serve(sys.stdin.buffer, sys.stdout.buffer)
    except Exception as e:  # noqa: BLE001
        print(f"dlm native host error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
