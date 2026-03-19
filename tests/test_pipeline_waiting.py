"""Tests for the pipeline waiting field."""
import json
import pathlib

from recap.pipeline import (
    PIPELINE_STAGES,
    _load_status,
    _mark_stage,
    _mark_waiting,
    _save_status,
)


def test_default_status_includes_waiting(tmp_path: pathlib.Path) -> None:
    """Default status dict should have waiting: None for every stage."""
    status = _load_status(tmp_path)
    for stage in PIPELINE_STAGES:
        assert "waiting" in status[stage], f"missing 'waiting' key in stage {stage}"
        assert status[stage]["waiting"] is None


def test_mark_waiting_sets_reason(tmp_path: pathlib.Path) -> None:
    """_mark_waiting should set the waiting field to the given reason."""
    status = _load_status(tmp_path)
    _mark_waiting(status, "diarize", "Awaiting speaker review")
    assert status["diarize"]["waiting"] == "Awaiting speaker review"


def test_mark_stage_clears_waiting(tmp_path: pathlib.Path) -> None:
    """_mark_stage should reset waiting to None."""
    status = _load_status(tmp_path)
    _mark_waiting(status, "diarize", "Awaiting speaker review")
    _mark_stage(status, "diarize", True)
    assert status["diarize"]["waiting"] is None


def test_waiting_persists_to_json(tmp_path: pathlib.Path) -> None:
    """Waiting field should be written to and read from status.json."""
    status = _load_status(tmp_path)
    _mark_waiting(status, "analyze", "Awaiting speaker review")
    _save_status(tmp_path, status)

    raw = json.loads((tmp_path / "status.json").read_text())
    assert raw["analyze"]["waiting"] == "Awaiting speaker review"

    reloaded = _load_status(tmp_path)
    assert reloaded["analyze"]["waiting"] == "Awaiting speaker review"
