"""FLAC to AAC audio conversion via ffmpeg."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)
FFMPEG_TIMEOUT_SECONDS = 300
FFPROBE_TIMEOUT_SECONDS = 15


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
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=FFMPEG_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"ffmpeg conversion timed out after {FFMPEG_TIMEOUT_SECONDS}s",
        ) from exc

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


def _probe_channel_count(audio_path: Path) -> int:
    """Return the channel count of the first audio stream via ffprobe.

    Used by :func:`ensure_mono_for_ml` to decide whether a mono sidecar is
    needed. Defaults to ``1`` if the probe output is unexpected rather than
    blowing up the pipeline -- the downstream stereo-check is a best-effort
    optimisation, not a correctness boundary.
    """
    cmd = [
        "ffprobe",
        "-v", "error",
        "-select_streams", "a:0",
        "-show_entries", "stream=channels",
        "-of", "json",
        str(audio_path),
    ]
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FFPROBE_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffprobe failed for {audio_path.name}: {result.stderr}")
    try:
        data = json.loads(result.stdout)
        streams = data.get("streams") or []
        if not streams:
            return 1
        return int(streams[0].get("channels", 1))
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"ffprobe returned unparseable output for {audio_path.name}: {exc}",
        ) from exc


def ensure_mono_for_ml(audio_path: Path) -> Path:
    """Ensure the audio has a mono representation suitable for ML model input.

    The recorder writes a 2-channel FLAC (mic + loopback, interleaved) so
    the pipeline has a channel-as-speaker-hint for diarization. NeMo's
    Parakeet ASR (``AudioToBPEDataset``) and Sortformer diarizer both
    expect shape ``(batch, time)`` -- i.e. mono -- and crash with
    ``Output shape expected = (batch, time) | Output shape found : torch.Size([1, T, 2])``
    when handed stereo input directly.

    Behaviour:

    - If ``audio_path`` is already mono, returns the original path
      unchanged (no sidecar, no extra ffmpeg run).
    - Otherwise, creates a mono sidecar alongside the original (suffix
      ``.mono.wav``) via ``ffmpeg -ac 1`` and returns the sidecar path.
      The stereo archive is untouched.

    The caller is responsible for deleting the sidecar once the ML
    stages finish (see pipeline __init__.py's transcribe/diarize block).
    """
    channels = _probe_channel_count(audio_path)
    if channels <= 1:
        return audio_path

    mono_path = audio_path.with_name(audio_path.stem + ".mono.wav")
    cmd = [
        "ffmpeg",
        "-y",
        "-i", str(audio_path),
        "-ac", "1",
        str(mono_path),
    ]
    logger.info(
        "Downmixing %s (%d channels) to mono sidecar for ML input",
        audio_path.name,
        channels,
    )
    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=FFMPEG_TIMEOUT_SECONDS,
    )
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg mono downmix failed: {result.stderr}")
    return mono_path


def delete_source_if_configured(flac_path: Path, delete: bool) -> None:
    """Optionally delete the source FLAC file after conversion.

    Args:
        flac_path: Path to the source file.
        delete: Whether to delete the file.
    """
    if delete and flac_path.exists():
        flac_path.unlink()
        logger.info("Deleted source file: %s", flac_path.name)
