"""Tests for resolve_recording_path shared helper (#28)."""
from __future__ import annotations

from pathlib import Path

from recap.artifacts import resolve_recording_path


def test_returns_flac_when_only_flac_exists(tmp_path: Path):
    (tmp_path / "rec.flac").touch()
    result = resolve_recording_path(tmp_path, "rec")
    assert result == tmp_path / "rec.flac"


def test_returns_m4a_when_only_m4a_exists(tmp_path: Path):
    (tmp_path / "rec.m4a").touch()
    result = resolve_recording_path(tmp_path, "rec")
    assert result == tmp_path / "rec.m4a"


def test_prefers_flac_when_both_exist(tmp_path: Path):
    (tmp_path / "rec.flac").touch()
    (tmp_path / "rec.m4a").touch()
    result = resolve_recording_path(tmp_path, "rec")
    assert result == tmp_path / "rec.flac"


def test_returns_none_when_neither_exists(tmp_path: Path):
    assert resolve_recording_path(tmp_path, "rec") is None


def test_handles_stem_with_spaces_and_unicode(tmp_path: Path):
    stem = "2026-04-24 Meeting élan"
    (tmp_path / f"{stem}.flac").touch()
    result = resolve_recording_path(tmp_path, stem)
    assert result == tmp_path / f"{stem}.flac"
