"""Validate the Chrome extension bundle (static checks, no browser)."""

from __future__ import annotations

import json
from pathlib import Path

EXT = Path(__file__).resolve().parents[1] / "extension"


def test_manifest_is_valid_mv3():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["manifest_version"] == 3
    assert manifest["name"]
    assert manifest["background"]["service_worker"] == "background.js"


def test_manifest_requests_required_permissions():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    perms = set(manifest["permissions"])
    assert {"downloads", "nativeMessaging"} <= perms


def test_background_wires_capture_to_native_host():
    js = (EXT / "background.js").read_text(encoding="utf-8")
    assert "com.dlm.native" in js
    assert "downloads.onCreated" in js
    assert "sendNativeMessage" in js


def test_referenced_files_exist():
    manifest = json.loads((EXT / "manifest.json").read_text(encoding="utf-8"))
    assert (EXT / manifest["background"]["service_worker"]).exists()
    assert (EXT / manifest["action"]["default_popup"]).exists()
    assert (EXT / "popup.js").exists()
