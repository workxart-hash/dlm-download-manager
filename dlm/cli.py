"""Command-line interface: ``python -m dlm get|resume``."""

from __future__ import annotations

import argparse
import sys
import threading
import time
from typing import List, Optional

from .engine import DownloadError, Downloader


def _human(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f}{unit}"
        n /= 1024


class _Progress:
    """Throttled single-line progress printer (speed + ETA) on stderr."""

    def __init__(self, quiet: bool = False):
        self.quiet = quiet
        self._lock = threading.Lock()
        self._start = time.monotonic()
        self._last = 0.0

    def __call__(self, done: int, total: int) -> None:
        if self.quiet:
            return
        now = time.monotonic()
        with self._lock:
            final = total and done >= total
            if not final and now - self._last < 0.1:
                return
            self._last = now
            elapsed = max(now - self._start, 1e-6)
            speed = done / elapsed
            pct = (done / total * 100) if total else 0.0
            eta = ((total - done) / speed) if (total and speed > 0) else 0.0
            sys.stderr.write(
                f"\r{pct:5.1f}%  {_human(done)}/{_human(total) if total else '?'}"
                f"  {_human(speed)}/s  ETA {eta:4.0f}s   "
            )
            sys.stderr.flush()
            if final:
                sys.stderr.write("\n")
                sys.stderr.flush()


def _run(downloader: Downloader, quiet: bool) -> int:
    try:
        path = downloader.download()
    except DownloadError as e:
        print(f"error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\ninterrupted (state saved; use `dlm resume`)", file=sys.stderr)
        return 130
    if not quiet:
        print(path)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="dlm", description="IDM-style download manager")
    sub = p.add_subparsers(dest="cmd", required=True)

    g = sub.add_parser("get", help="download a URL")
    g.add_argument("url")
    g.add_argument("-o", "--output", help="output file (default: name from URL)")
    g.add_argument("-s", "--segments", type=int, default=8,
                   help="number of parallel segments (default 8, max 32)")
    g.add_argument("--max-retries", type=int, default=5)
    g.add_argument("--no-dynamic", action="store_true",
                   help="disable dynamic segmentation")
    g.add_argument("--sha256", help="expected SHA-256 of the finished file")
    g.add_argument("-q", "--quiet", action="store_true")

    r = sub.add_parser("resume", help="resume from a .json state file")
    r.add_argument("state")
    r.add_argument("--max-retries", type=int, default=5)
    r.add_argument("-q", "--quiet", action="store_true")

    sub.add_parser("gui", help="launch the graphical interface (PySide6)")

    sub.add_parser("native-host", help="run the native-messaging host (invoked by Chrome)")
    ih = sub.add_parser("install-host", help="register the native host with Chrome")
    ih.add_argument("extension_id", help="the unpacked extension's ID from chrome://extensions")
    sub.add_parser("uninstall-host", help="unregister the native host")
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)

    if args.cmd == "get":
        d = Downloader(
            args.url,
            dest=args.output,
            segments=args.segments,
            max_retries=args.max_retries,
            dynamic=not args.no_dynamic,
            expected_sha256=args.sha256,
            on_progress=_Progress(args.quiet),
        )
        return _run(d, args.quiet)

    if args.cmd == "resume":
        d = Downloader.from_state_file(
            args.state,
            max_retries=args.max_retries,
            on_progress=_Progress(args.quiet),
        )
        return _run(d, args.quiet)

    if args.cmd == "gui":
        try:
            from .gui.app import run as run_gui
        except ImportError:
            print("error: GUI needs PySide6 (pip install PySide6-Essentials)",
                  file=sys.stderr)
            return 1
        return run_gui()

    if args.cmd == "native-host":
        from .native.host import main as host_main
        return host_main()

    if args.cmd == "install-host":
        from .native.install import install_host
        try:
            paths = install_host(args.extension_id)
        except Exception as e:  # noqa: BLE001
            print(f"error: {e}", file=sys.stderr)
            return 1
        print("registered native host 'com.dlm.native':")
        print(f"  manifest: {paths['manifest']}")
        print(f"  launcher: {paths['launcher']}")
        return 0

    if args.cmd == "uninstall-host":
        from .native.install import uninstall_host
        uninstall_host()
        print("unregistered native host 'com.dlm.native'")
        return 0

    return 2


if __name__ == "__main__":
    sys.exit(main())
