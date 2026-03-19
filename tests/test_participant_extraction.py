"""Tests for screenshot-based participant extraction."""
import json
import pathlib
from unittest.mock import patch

import pytest

from recap.pipeline import extract_participants_from_screenshots


class TestParticipantExtraction:
    def test_returns_names_from_claude_response(self, tmp_path):
        screenshot = tmp_path / "frame_00030.png"
        screenshot.write_bytes(b"fake png data")
        with patch("recap.pipeline.run_claude_cli") as mock_claude:
            mock_claude.return_value = '["Jane Smith", "Bob Jones"]'
            result = extract_participants_from_screenshots([screenshot])
        assert result == ["Bob Jones", "Jane Smith"]

    def test_unions_names_across_multiple_screenshots(self, tmp_path):
        screenshots = []
        for i in range(3):
            f = tmp_path / f"frame_{i:05d}.png"
            f.write_bytes(b"fake png data")
            screenshots.append(f)
        with patch("recap.pipeline.run_claude_cli") as mock_claude:
            mock_claude.side_effect = [
                '["Jane Smith", "Bob Jones"]',
                '["Jane Smith", "Alice Chen"]',
                '["Bob Jones", "David Park"]',
            ]
            result = extract_participants_from_screenshots(screenshots)
        assert sorted(result) == ["Alice Chen", "Bob Jones", "David Park", "Jane Smith"]

    def test_empty_on_no_screenshots(self):
        result = extract_participants_from_screenshots([])
        assert result == []

    def test_handles_empty_claude_response(self, tmp_path):
        screenshot = tmp_path / "frame_00030.png"
        screenshot.write_bytes(b"fake png data")
        with patch("recap.pipeline.run_claude_cli") as mock_claude:
            mock_claude.return_value = "[]"
            result = extract_participants_from_screenshots([screenshot])
        assert result == []

    def test_handles_claude_error(self, tmp_path):
        screenshot = tmp_path / "frame_00030.png"
        screenshot.write_bytes(b"fake png data")
        with patch("recap.pipeline.run_claude_cli") as mock_claude:
            mock_claude.side_effect = Exception("Claude CLI failed")
            result = extract_participants_from_screenshots([screenshot])
        assert result == []
