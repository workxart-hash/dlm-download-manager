"""Integration tests for the `python -m dlm` command-line interface."""

from __future__ import annotations

import hashlib

from dlm.cli import main
from dlm.engine import Downloader, DownloadError
from dlm.state import default_state_path

PAYLOAD = bytes((i * 29 + 3) % 256 for i in range(300_000))


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_cli_get_downloads_file(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    code = main(["get", url, "-o", str(dest), "--segments", "4", "--max-retries", "2"])
    assert code == 0
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)


def test_cli_get_with_matching_sha256_succeeds(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    code = main(["get", url, "-o", str(dest), "--sha256", _sha(PAYLOAD)])
    assert code == 0


def test_cli_get_with_wrong_sha256_fails(server, tmp_path):
    url = server.configure(PAYLOAD)
    dest = tmp_path / "out.bin"
    code = main(["get", url, "-o", str(dest), "--sha256", "00" * 32])
    assert code != 0


def test_cli_resume_completes_interrupted_download(server, tmp_path):
    dest = tmp_path / "out.bin"

    # Leave an interrupted download behind (state file + partial parts).
    url = server.configure(PAYLOAD, fail_once=True)
    try:
        Downloader(url, dest=dest, segments=4, max_retries=0,
                   retry_backoff=0, dynamic=False).download()
    except DownloadError:
        pass

    url = server.configure(PAYLOAD, fail_once=False)
    code = main(["resume", str(default_state_path(dest))])
    assert code == 0
    assert _sha(dest.read_bytes()) == _sha(PAYLOAD)
