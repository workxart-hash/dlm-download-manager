"""Resume state: a small JSON sidecar describing an in-progress download.

The file records the current segment table and enough server metadata
(total size + ETag) to detect when a partially downloaded file is stale and
must be restarted rather than resumed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

Segment = Tuple[int, int]


@dataclass
class DownloadState:
    url: str
    dest: str
    total: int
    etag: Optional[str]
    accept_ranges: bool
    segments: List[Segment]
    sha256: Optional[str] = None

    def save(self, path) -> None:
        data = {
            "url": self.url,
            "dest": self.dest,
            "total": self.total,
            "etag": self.etag,
            "accept_ranges": self.accept_ranges,
            "segments": [[s, e] for s, e in self.segments],
            "sha256": self.sha256,
        }
        tmp = Path(str(path) + ".tmp")
        tmp.write_text(json.dumps(data, indent=2))
        tmp.replace(path)  # atomic-ish: never leave a half-written state file

    @classmethod
    def load(cls, path) -> "DownloadState":
        data = json.loads(Path(path).read_text())
        return cls(
            url=data["url"],
            dest=data["dest"],
            total=data["total"],
            etag=data.get("etag"),
            accept_ranges=data["accept_ranges"],
            segments=[tuple(x) for x in data["segments"]],
            sha256=data.get("sha256"),
        )


def default_state_path(dest) -> Path:
    return Path(str(dest) + ".dlm.json")


def is_resumable(state: DownloadState, remote_total: int, remote_etag: Optional[str]) -> bool:
    """Whether existing partial data is still valid for the current remote file."""
    if state.total != remote_total:
        return False
    if state.etag is not None and remote_etag is not None:
        return state.etag == remote_etag
    # If either side has no ETag, trust the size match.
    return True
