"""Recovery module for finding orphaned FLAC files from crashed recordings."""
from __future__ import annotations

import json
from pathlib import Path


def find_orphaned_recordings(
    recordings_path: Path,
    status_dir: Path,
) -> list[Path]:
    """Find FLAC files that lack a completed pipeline status.

    Scans *recordings_path* for ``.flac`` files and checks each against its
    corresponding status JSON.  A FLAC is considered orphaned when:

    - No status file exists for it, **or**
    - The status file exists but ``pipeline-status`` is not ``"complete"``.

    Args:
        recordings_path: Directory containing FLAC recordings.
        status_dir: Directory containing per-recording status JSON files.

    Returns:
        List of :class:`~pathlib.Path` objects for orphaned FLAC files.
        Returns an empty list when *recordings_path* does not exist or
        contains no FLAC files.
    """
    if not recordings_path.is_dir():
        return []

    orphans: list[Path] = []
    for flac in sorted(recordings_path.glob("*.flac")):
        status_file = status_dir / f"{flac.stem}.json"
        if _is_completed(status_file):
            continue
        orphans.append(flac)

    return orphans


def _is_completed(status_file: Path) -> bool:
    """Return True if *status_file* exists and records a completed pipeline."""
    if not status_file.is_file():
        return False
    try:
        data = json.loads(status_file.read_text(encoding="utf-8"))
        return data.get("pipeline-status") == "complete"
    except (json.JSONDecodeError, OSError):
        return False
