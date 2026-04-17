"""Tests for audio format conversion."""
import pytest
from unittest.mock import patch, MagicMock
from recap.pipeline.audio_convert import (
    convert_flac_to_aac,
    delete_source_if_configured,
    ensure_mono_for_ml,
)


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
        delete_source_if_configured(flac, delete=True)
        assert not flac.exists()  # still doesn't exist, no error raised


class TestEnsureMonoForMl:
    """The recorder writes a 2-channel FLAC (mic + loopback interleaved) so
    we can preserve the channel-as-speaker-hint for diarization, but
    Parakeet's AudioToBPEDataset (and Sortformer) require mono input. This
    helper produces a mono sidecar for ML input while leaving the stereo
    archive intact. See the `Output shape expected = (batch, time)` crash
    that this helper resolves.
    """

    def test_mono_input_returns_original_path_unchanged(self, tmp_path):
        audio = tmp_path / "rec.flac"
        audio.write_bytes(b"fake")

        def mock_run(cmd, *args, **kwargs):
            # ffprobe is called first; report 1 channel so we short-circuit.
            if "ffprobe" in str(cmd[0]):
                return MagicMock(returncode=0, stdout='{"streams":[{"channels":1}]}')
            # ffmpeg should never be reached for mono input.
            raise AssertionError(f"Unexpected subprocess call for mono input: {cmd}")

        with patch("subprocess.run", side_effect=mock_run):
            result = ensure_mono_for_ml(audio)

        assert result == audio

    def test_stereo_input_writes_mono_sidecar(self, tmp_path):
        audio = tmp_path / "rec.flac"
        audio.write_bytes(b"fake")

        calls: list[list[str]] = []

        def mock_run(cmd, *args, **kwargs):
            calls.append(list(cmd))
            if "ffprobe" in str(cmd[0]):
                return MagicMock(returncode=0, stdout='{"streams":[{"channels":2}]}')
            # ffmpeg downmix call: touch the expected output so helper sees it.
            out_path = cmd[-1]
            from pathlib import Path as _Path
            _Path(out_path).write_bytes(b"mono-fake")
            return MagicMock(returncode=0)

        with patch("subprocess.run", side_effect=mock_run):
            result = ensure_mono_for_ml(audio)

        # Returned a sidecar distinct from the original archive.
        assert result != audio
        assert result.exists()
        # Original stereo archive untouched.
        assert audio.exists()
        assert audio.read_bytes() == b"fake"

        # ffmpeg was invoked with -ac 1 (force mono downmix).
        ffmpeg_calls = [c for c in calls if "ffmpeg" in str(c[0])]
        assert len(ffmpeg_calls) == 1
        cmd = ffmpeg_calls[0]
        ac_idx = cmd.index("-ac")
        assert cmd[ac_idx + 1] == "1"

    def test_raises_runtime_error_when_ffmpeg_fails(self, tmp_path):
        audio = tmp_path / "rec.flac"
        audio.write_bytes(b"fake")

        def mock_run(cmd, *args, **kwargs):
            if "ffprobe" in str(cmd[0]):
                return MagicMock(returncode=0, stdout='{"streams":[{"channels":2}]}')
            return MagicMock(returncode=1, stderr="ffmpeg boom")

        with patch("subprocess.run", side_effect=mock_run):
            with pytest.raises(RuntimeError, match="ffmpeg"):
                ensure_mono_for_ml(audio)
