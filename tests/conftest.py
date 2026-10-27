"""Test harness: a real local HTTP server with configurable Range behaviour.

Per the SPEC it must be able to:
  * serve a temporary file of random bytes
  * honour ``Range: bytes=start-end`` with ``206`` (or ignore it and send ``200``)
  * drop the connection half-way through the first response for a given range
  * delay ranges other than the first, so dynamic segmentation can be triggered
    deterministically (segment 0 finishes first and steals work)
  * report how many body bytes went on the wire (to prove a resume transferred
    less than the whole file)
"""

from __future__ import annotations

import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

_RANGE_RE = re.compile(r"bytes=(\d+)-(\d*)")


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):  # silence test logging
        pass

    @property
    def cfg(self):
        return self.server.cfg  # type: ignore[attr-defined]

    def do_HEAD(self):
        data = self.cfg["data"]
        self.send_response(200)
        if self.cfg["accept_ranges"]:
            self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("ETag", self.cfg["etag"])
        self.end_headers()

    def do_GET(self):
        data = self.cfg["data"]
        total = len(data)
        rng = self.headers.get("Range")

        if rng and self.cfg["accept_ranges"]:
            m = _RANGE_RE.match(rng.strip())
            start = int(m.group(1))
            end = int(m.group(2)) if m.group(2) else total - 1
            body = data[start : end + 1]
            self.send_response(206)
            self.send_header("Content-Range", f"bytes {start}-{end}/{total}")
            self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("ETag", self.cfg["etag"])
            self.end_headers()
            self._write_body(body, range_start=start)
        else:
            self.send_response(200)
            if self.cfg["accept_ranges"]:
                self.send_header("Accept-Ranges", "bytes")
            self.send_header("Content-Length", str(total))
            self.send_header("ETag", self.cfg["etag"])
            self.end_headers()
            self._write_body(data, range_start=0)

    def _write_body(self, body: bytes, range_start: int):
        srv = self.server
        # Delay every range except the one starting at 0, so the first segment
        # wins the race and triggers dynamic segmentation.
        if self.cfg["delay"] and range_start > 0:
            time.sleep(self.cfg["delay"])

        if self.cfg["fail_once"]:
            do_fail = False
            half = 0
            with srv.lock:  # type: ignore[attr-defined]
                # Drop the first request for each segment exactly once. The point
                # the client resumes from (start + half) is whitelisted so the
                # retry always succeeds: a transient blip, not a permanent fault.
                if (range_start not in srv.passthrough  # type: ignore[attr-defined]
                        and range_start not in srv.failed):  # type: ignore[attr-defined]
                    half = max(1, len(body) // 2)
                    srv.failed.add(range_start)  # type: ignore[attr-defined]
                    srv.passthrough.add(range_start + half)  # type: ignore[attr-defined]
                    do_fail = True
            if do_fail:
                self._served(half)
                try:
                    self.wfile.write(body[:half])
                    self.wfile.flush()
                    # Let the client actually receive and commit the partial data
                    # before we drop, mimicking a real mid-stream disconnect
                    # (rather than an RST that discards the in-flight buffer).
                    time.sleep(0.1)
                except OSError:
                    pass
                self.close_connection = True
                try:
                    self.connection.close()
                except OSError:
                    pass
                return

        self._served(len(body))
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def _served(self, n: int):
        with self.server.lock:  # type: ignore[attr-defined]
            self.server.bytes_served += n  # type: ignore[attr-defined]


class ServerControl:
    def __init__(self, server: ThreadingHTTPServer):
        self._server = server
        host, port = server.server_address
        self.base_url = f"http://{host}:{port}"

    def configure(self, data: bytes, *, accept_ranges: bool = True,
                  fail_once: bool = False, delay: float = 0.0, etag: str = '"v1"'):
        srv = self._server
        srv.cfg.update(  # type: ignore[attr-defined]
            data=data, accept_ranges=accept_ranges,
            fail_once=fail_once, delay=delay, etag=etag,
        )
        with srv.lock:  # type: ignore[attr-defined]
            srv.failed.clear()  # type: ignore[attr-defined]
            srv.passthrough.clear()  # type: ignore[attr-defined]
            srv.bytes_served = 0  # type: ignore[attr-defined]
        return self.base_url + "/file.bin"

    @property
    def bytes_served(self) -> int:
        with self._server.lock:  # type: ignore[attr-defined]
            return self._server.bytes_served  # type: ignore[attr-defined]


@pytest.fixture
def server():
    srv = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.cfg = {"data": b"", "accept_ranges": True, "fail_once": False,
               "delay": 0.0, "etag": '"v1"'}
    srv.failed = set()
    srv.passthrough = set()
    srv.bytes_served = 0
    srv.lock = threading.Lock()
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    try:
        yield ServerControl(srv)
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=5)
