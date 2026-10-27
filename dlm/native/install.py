"""Register (and unregister) the native-messaging host with Chrome.

``build_host_manifest`` is pure and unit-tested. ``install_host`` writes a
``.bat`` launcher + the manifest JSON and points Chrome at it via the Windows
registry; ``uninstall_host`` reverses that.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import List

HOST_NAME = "com.dlm.native"
_REGISTRY_PATH = rf"Software\Google\Chrome\NativeMessagingHosts\{HOST_NAME}"


def build_host_manifest(bat_path: str, extension_ids: List[str],
                        description: str = "dlm download manager") -> dict:
    return {
        "name": HOST_NAME,
        "description": description,
        "path": bat_path,
        "type": "stdio",
        "allowed_origins": [f"chrome-extension://{eid}/" for eid in extension_ids],
    }


def _project_root() -> Path:
    # .../dlm/native/install.py -> project root is two levels above the package
    return Path(__file__).resolve().parents[2]


def launcher_text(executable: str, project_root: str, frozen: bool) -> str:
    """Return the .bat wrapper Chrome invokes to start the native host.

    Frozen: the bundled exe already knows the ``native-host`` subcommand.
    Source: run the module from the interpreter, with the project on PYTHONPATH
    so it works without a pip install.
    """
    if frozen:
        return f'@echo off\r\n"{executable}" native-host %*\r\n'
    return (
        "@echo off\r\n"
        f'set "PYTHONPATH={project_root};%PYTHONPATH%"\r\n'
        f'"{executable}" -m dlm.native.host %*\r\n'
    )


def _write_launcher(install_dir: Path, python: str) -> Path:
    bat = install_dir / "dlm_host.bat"
    frozen = bool(getattr(sys, "frozen", False))
    executable = sys.executable if frozen else python
    bat.write_text(launcher_text(executable, str(_project_root()), frozen),
                   encoding="utf-8")
    return bat


def install_host(extension_id: str, install_dir=None, python: str = None) -> dict:
    """Install the host for the current user. Windows + Chrome."""
    import winreg  # Windows only

    install_dir = Path(install_dir) if install_dir else Path.home() / ".dlm"
    install_dir.mkdir(parents=True, exist_ok=True)
    python = python or sys.executable

    bat = _write_launcher(install_dir, python)
    manifest = build_host_manifest(str(bat), [extension_id])
    manifest_path = install_dir / f"{HOST_NAME}.json"
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")

    key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, _REGISTRY_PATH)
    try:
        winreg.SetValueEx(key, "", 0, winreg.REG_SZ, str(manifest_path))
    finally:
        winreg.CloseKey(key)

    return {"manifest": str(manifest_path), "launcher": str(bat)}


def uninstall_host() -> None:
    import winreg

    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, _REGISTRY_PATH)
    except FileNotFoundError:
        pass
