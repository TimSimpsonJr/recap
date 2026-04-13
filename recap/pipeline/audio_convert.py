"""FLAC to AAC audio conversion via ffmpeg."""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_flac_to_aac(flac_path: Path, bitrate: str = "64k") -> Path:
    """Convert a FLAC file to AAC in an M4A container.

    Args:
        flac_path: Path to the source FLAC file.
        bitrate: AAC bitrate (default "64k").

    Returns:
        Path to the output .m4a file.

    Raises:
        RuntimeError: If ffmpeg exits with a non-zero return code.
    """
    output_path = flac_path.with_suffix(".m4a")
    input_size = flac_path.stat().st_size

    cmd = [
        "ffmpeg",
        "-i", str(flac_path),
        "-c:a", "aac",
        "-b:a", bitrate,
        "-y",
        str(output_path),
    ]

    logger.info("Converting %s to AAC (%s)", flac_path.name, bitrate)
    result = subprocess.run(cmd, capture_output=True, text=True)

    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg conversion failed: {result.stderr}")

    output_size = output_path.stat().st_size if output_path.exists() else 0
    logger.info(
        "Conversion complete: %s (%d bytes) -> %s (%d bytes)",
        flac_path.name,
        input_size,
        output_path.name,
        output_size,
    )
    return output_path


def delete_source_if_configured(flac_path: Path, delete: bool) -> None:
    """Optionally delete the source FLAC file after conversion.

    Args:
        flac_path: Path to the source file.
        delete: Whether to delete the file.
    """
    if delete and flac_path.exists():
        flac_path.unlink()
        logger.info("Deleted source file: %s", flac_path.name)
