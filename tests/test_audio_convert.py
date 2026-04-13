"""Tests for audio format conversion."""
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path
from recap.pipeline.audio_convert import convert_flac_to_aac, delete_source_if_configured


class TestConvertFlacToAac:
    def test_output_path_has_m4a_extension(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            result = convert_flac_to_aac(flac_path)
        assert result.suffix == ".m4a"
        assert result.stem == "recording"

    def test_calls_ffmpeg(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            convert_flac_to_aac(flac_path)
        cmd = mock_run.call_args[0][0]
        assert "ffmpeg" in str(cmd[0])
        assert str(flac_path) in cmd

    def test_raises_on_ffmpeg_failure(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="codec error")
            with pytest.raises(RuntimeError, match="ffmpeg"):
                convert_flac_to_aac(flac_path)

    def test_custom_bitrate(self, tmp_path):
        flac_path = tmp_path / "recording.flac"
        flac_path.write_bytes(b"fake")
        with patch("subprocess.run") as mock_run:
            mock_run.return_value = MagicMock(returncode=0)
            convert_flac_to_aac(flac_path, bitrate="128k")
        cmd = str(mock_run.call_args[0][0])
        assert "128k" in cmd


class TestDeleteSource:
    def test_deletes_when_configured(self, tmp_path):
        flac = tmp_path / "test.flac"
        flac.write_bytes(b"data")
        delete_source_if_configured(flac, delete=True)
        assert not flac.exists()

    def test_keeps_when_not_configured(self, tmp_path):
        flac = tmp_path / "test.flac"
        flac.write_bytes(b"data")
        delete_source_if_configured(flac, delete=False)
        assert flac.exists()

    def test_no_error_if_missing(self, tmp_path):
        flac = tmp_path / "nonexistent.flac"
        delete_source_if_configured(flac, delete=True)  # should not raise
