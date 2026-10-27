"""Unit tests for the native-messaging host: framing codec, message dispatch,
the serve loop, and host-manifest generation. No Chrome required."""

from __future__ import annotations

import io
import json
import struct

import pytest

from dlm.native.host import handle_message, serve
from dlm.native.install import build_host_manifest, launcher_text
from dlm.native.protocol import read_message, write_message


# -- framing codec ----------------------------------------------------------

def test_write_then_read_round_trips():
    buf = io.BytesIO()
    write_message(buf, {"type": "download", "url": "http://x/y.bin"})
    buf.seek(0)
    assert read_message(buf) == {"type": "download", "url": "http://x/y.bin"}


def test_frame_has_little_endian_length_prefix():
    buf = io.BytesIO()
    write_message(buf, {"a": 1})
    raw = buf.getvalue()
    payload = json.dumps({"a": 1}, separators=(",", ":")).encode()
    assert raw[:4] == struct.pack("=I", len(payload))
    assert raw[4:] == payload


def test_read_returns_none_at_eof():
    assert read_message(io.BytesIO(b"")) is None


def test_read_raises_on_truncated_body():
    # claims 10 bytes, provides 3
    bad = struct.pack("=I", 10) + b"abc"
    with pytest.raises(EOFError):
        read_message(io.BytesIO(bad))


def test_unicode_payload_round_trips():
    buf = io.BytesIO()
    write_message(buf, {"filename": "lagu—kôtā.mp3"})
    buf.seek(0)
    assert read_message(buf)["filename"] == "lagu—kôtā.mp3"


# -- message dispatch -------------------------------------------------------

def test_ping_is_answered():
    resp = handle_message({"type": "ping"}, launcher=lambda *a, **k: None)
    assert resp["ok"] is True and resp.get("pong") is True


def test_download_invokes_launcher_and_acks():
    calls = []
    resp = handle_message(
        {"type": "download", "url": "http://h/f.bin", "filename": "f.bin"},
        launcher=lambda url, filename, options: calls.append((url, filename)),
    )
    assert resp["ok"] is True
    assert calls == [("http://h/f.bin", "f.bin")]


def test_download_without_url_is_rejected():
    resp = handle_message({"type": "download"}, launcher=lambda *a, **k: None)
    assert resp["ok"] is False


def test_unknown_type_is_rejected():
    resp = handle_message({"type": "nope"}, launcher=lambda *a, **k: None)
    assert resp["ok"] is False


# -- serve loop -------------------------------------------------------------

def test_serve_processes_all_messages_until_eof():
    inp = io.BytesIO()
    write_message(inp, {"type": "download", "url": "http://h/a"})
    write_message(inp, {"type": "download", "url": "http://h/b"})
    inp.seek(0)
    out = io.BytesIO()
    calls = []
    serve(inp, out, launcher=lambda url, filename, options: calls.append(url))

    assert calls == ["http://h/a", "http://h/b"]
    out.seek(0)
    r1 = read_message(out)
    r2 = read_message(out)
    assert r1["ok"] and r2["ok"]
    assert read_message(out) is None  # nothing more written


# -- host manifest ----------------------------------------------------------

def test_host_main_handles_empty_stdin(monkeypatch):
    import sys as _sys
    from dlm.native import host
    monkeypatch.setattr(_sys, "stdin", type("S", (), {"buffer": io.BytesIO(b"")})())
    monkeypatch.setattr(_sys, "stdout", type("S", (), {"buffer": io.BytesIO()})())
    assert host.main() == 0


def test_host_manifest_fields():
    m = build_host_manifest("C:/path/dlm_host.bat", ["abcdef123"])
    assert m["name"] == "com.dlm.native"
    assert m["type"] == "stdio"
    assert m["path"] == "C:/path/dlm_host.bat"
    assert m["allowed_origins"] == ["chrome-extension://abcdef123/"]


def test_launcher_text_source_mode_runs_module():
    txt = launcher_text("C:/py/python.exe", "D:/proj", frozen=False)
    assert "-m dlm.native.host" in txt
    assert "PYTHONPATH=D:/proj" in txt


def test_launcher_text_frozen_mode_calls_subcommand():
    txt = launcher_text("C:/app/dlm.exe", "D:/proj", frozen=True)
    assert '"C:/app/dlm.exe" native-host' in txt
    assert "PYTHONPATH" not in txt  # the exe carries its own deps
