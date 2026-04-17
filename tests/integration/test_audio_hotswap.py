"""Opt-in hardware test for audio hot-swap.

Run with: ``uv run pytest tests/integration/test_audio_hotswap.py -m hardware -s``

Not wired into CI (excluded via ``-m 'not integration and not hardware'`` in
pyproject addopts). Exercises the real PyAudio + soxr path end-to-end so
the operator can verify the "device changes mid-meeting" design target on
their own audio hardware.

During a run the operator can:

- Leave devices alone -> smoke test.
- Plug/unplug a USB mic mid-recording -> exercises reopen path.
- Swap default output (headphones vs speakers) mid-recording -> exercises
  the loopback reopen path.
- Disconnect both inputs briefly -> exercises the DEGRADED recovery path.
"""
from __future__ import annotations

import pathlib
import time

import pytest


@pytest.mark.hardware
def test_record_10s_logs_no_errors(tmp_path: pathlib.Path) -> None:
    """Record for 10 seconds and assert the FLAC is non-empty and no
    fatal capture error surfaces. During the run the operator may
    manually swap default audio devices to exercise the hot-swap logic."""
    from recap.daemon.recorder.audio import AudioCapture

    out = tmp_path / "hotswap_smoke.flac"
    cap = AudioCapture(output_path=out, sample_rate=48000)
    cap.start()
    try:
        time.sleep(10)
    finally:
        cap.stop()
    assert out.exists()
    assert out.stat().st_size > 0
    assert cap._fatal_error is None
