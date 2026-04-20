"""Tests for ``_run_with_retry`` classification-aware retry behavior.

GPU out-of-memory failures must NOT be retried: retrying the same
whole-file allocation path 30 seconds later only adds host stress
without changing the outcome, and on 2026-04-20 this retry path
contributed to a hard system crash (see
``docs/handoffs/2026-04-20-meeting-detection-test.md``).

Non-OOM failures (network blips, transient I/O errors) must continue
to retry under ``auto_retry`` so the existing resilience contract is
preserved.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from recap.pipeline import PipelineRuntimeConfig, _run_with_retry


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def retry_enabled_config(tmp_path) -> PipelineRuntimeConfig:
    """Config that would normally retry (mirrors config.yaml default)."""
    return PipelineRuntimeConfig(
        auto_retry=True,
        max_retries=1,
        status_dir=tmp_path / "status",
    )


@pytest.fixture(autouse=True)
def _no_real_sleep():
    """Short-circuit ``time.sleep`` so the 30s retry backoff doesn't
    block the test suite. The retry decision we're asserting is
    independent of the actual sleep duration.
    """
    with patch("recap.pipeline.time.sleep"):
        yield


# ---------------------------------------------------------------------------
# OOM short-circuit: transcribe
# ---------------------------------------------------------------------------

def test_run_with_retry_skips_retry_on_cuda_oom_in_transcribe(
    retry_enabled_config: PipelineRuntimeConfig,
) -> None:
    """A CUDA OOM in transcribe must fail on the first attempt."""
    attempts: list[int] = []
    oom = RuntimeError(
        "CUDA out of memory. Tried to allocate 46.19 GiB. "
        "GPU 0 has a total capacity of 11.99 GiB.",
    )

    def failing_transcribe():
        attempts.append(1)
        raise oom

    with pytest.raises(RuntimeError, match="out of memory"):
        _run_with_retry(
            failing_transcribe,
            stage="transcribe",
            config=retry_enabled_config,
            recording_stem="2026-04-20-155927-disbursecloud",
            note_path=None,
        )

    assert len(attempts) == 1, (
        f"OOM must not be retried; got {len(attempts)} attempt(s). "
        "Retrying the same whole-file Parakeet allocation is a known "
        "host-crash path."
    )


# ---------------------------------------------------------------------------
# OOM short-circuit: diarize (shared retry wrapper)
# ---------------------------------------------------------------------------

def test_run_with_retry_skips_retry_on_cuda_oom_in_diarize(
    retry_enabled_config: PipelineRuntimeConfig,
) -> None:
    """Same OOM rule applies to diarize since the wrapper is shared."""
    attempts: list[int] = []
    oom = RuntimeError("CUDA out of memory during NeMo forward pass")

    def failing_diarize():
        attempts.append(1)
        raise oom

    with pytest.raises(RuntimeError, match="out of memory"):
        _run_with_retry(
            failing_diarize,
            stage="diarize",
            config=retry_enabled_config,
            recording_stem="test-stem",
            note_path=None,
        )

    assert len(attempts) == 1, (
        f"OOM must not be retried on diarize either; got {len(attempts)} attempt(s)."
    )


# ---------------------------------------------------------------------------
# Sanity: non-OOM errors still retry under auto_retry
# ---------------------------------------------------------------------------

def test_run_with_retry_still_retries_transient_non_oom_errors(
    retry_enabled_config: PipelineRuntimeConfig,
) -> None:
    """A transient non-OOM failure still gets one retry and then succeeds."""
    attempts: list[int] = []

    def flaky():
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("Connection reset while downloading model")
        return "transcript"

    result = _run_with_retry(
        flaky,
        stage="transcribe",
        config=retry_enabled_config,
        recording_stem="test-stem",
        note_path=None,
    )

    assert result == "transcript"
    assert len(attempts) == 2, (
        f"Non-OOM transient error should retry once; got {len(attempts)} attempt(s)."
    )


def test_run_with_retry_oom_in_non_gpu_stage_also_skipped(
    retry_enabled_config: PipelineRuntimeConfig,
) -> None:
    """OOM is non-retryable regardless of stage.

    The rule is about the error shape, not the stage. If an analyze
    or export path ever raises an OOM, retrying the same allocation
    helps no one.
    """
    attempts: list[int] = []

    def failing_export():
        attempts.append(1)
        raise RuntimeError("out of memory: allocation failed")

    with pytest.raises(RuntimeError, match="out of memory"):
        _run_with_retry(
            failing_export,
            stage="export",
            config=retry_enabled_config,
            recording_stem="test-stem",
            note_path=None,
        )

    assert len(attempts) == 1
