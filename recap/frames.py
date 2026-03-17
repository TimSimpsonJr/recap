"""Frame extraction from video via ffmpeg scene detection."""
from __future__ import annotations

import logging
import pathlib
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FrameResult:
    path: pathlib.Path
    timestamp: float


def _parse_scene_timestamps(ffprobe_output: str) -> list[float]:
    timestamps = []
    for line in ffprobe_output.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                timestamps.append(float(line))
            except ValueError:
                continue
    return timestamps


def extract_frames(
    video_path: pathlib.Path,
    output_dir: pathlib.Path,
    scene_threshold: float = 0.3,
) -> list[FrameResult]:
    stem = video_path.stem

    # Detect scene changes using ffprobe
    logger.info("Detecting scene changes in %s (threshold=%.1f)", video_path, scene_threshold)
    probe_result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-f", "lavfi",
            "-i", f"movie={str(video_path)},select=gt(scene\\,{scene_threshold})",
            "-show_entries", "frame=pts_time",
            "-of", "csv=p=0",
        ],
        capture_output=True,
        text=True,
    )

    if probe_result.returncode != 0:
        logger.warning(
            "Scene detection failed (likely audio-only file): %s",
            probe_result.stderr[:200] if probe_result.stderr else "no stderr",
        )
        return []

    timestamps = _parse_scene_timestamps(probe_result.stdout)
    if not timestamps:
        logger.info("No scene changes detected")
        return []

    logger.info("Found %d scene changes, extracting frames", len(timestamps))

    results = []
    for ts in timestamps:
        filename = f"{stem}-{ts:07.3f}.png"
        out_path = output_dir / filename

        extract_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss", str(ts),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )

        if extract_result.returncode == 0 and out_path.exists():
            results.append(FrameResult(path=out_path, timestamp=ts))
        else:
            logger.warning("Failed to extract frame at %.3fs", ts)

    logger.info("Extracted %d frames", len(results))
    return results
