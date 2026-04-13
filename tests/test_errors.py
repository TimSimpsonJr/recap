"""Tests for recap.errors.map_error."""
from recap.errors import map_error


def test_cuda_unavailable_transcribe():
    err = RuntimeError("CUDA not available")
    result = map_error("transcribe", err)
    assert "CUDA not available" in result


def test_gpu_oom_transcribe():
    err = RuntimeError("CUDA out of memory")
    result = map_error("transcribe", err)
    assert "GPU out of memory" in result
    assert "Parakeet" in result


def test_model_download_failure_transcribe():
    err = RuntimeError("Failed to download model: connection refused")
    result = map_error("transcribe", err)
    assert "Parakeet" in result
    assert "internet" in result.lower()


def test_audio_file_not_found_transcribe():
    err = FileNotFoundError("recording.flac")
    result = map_error("transcribe", err)
    assert "Audio file not found" in result


def test_cuda_unavailable_diarize():
    err = RuntimeError("CUDA not available")
    result = map_error("diarize", err)
    assert "CUDA not available" in result


def test_gpu_oom_diarize():
    err = RuntimeError("CUDA out of memory")
    result = map_error("diarize", err)
    assert "GPU out of memory" in result
    assert "diarization" in result


def test_model_download_failure_diarize():
    err = RuntimeError("Failed to download NeMo model: connection error")
    result = map_error("diarize", err)
    assert "NeMo" in result


def test_claude_not_found():
    err = FileNotFoundError("No such file: claude")
    result = map_error("analyze", err, command="/usr/bin/claude")
    assert "Claude CLI not found" in result


def test_vault_missing():
    err = FileNotFoundError("Path not found")
    result = map_error("export", err, vault_path="/foo/vault")
    assert "Vault path does not exist" in result


def test_ffmpeg_not_found_convert():
    err = RuntimeError("ffmpeg not found in PATH")
    result = map_error("convert", err)
    assert "ffmpeg not found" in result


def test_convert_file_not_found():
    err = FileNotFoundError("recording.flac missing")
    result = map_error("convert", err)
    assert "Recording file not found" in result


def test_unknown_error_passthrough():
    err = ValueError("something unexpected")
    result = map_error("transcribe", err)
    assert result == "something unexpected"


def test_disk_full():
    err = OSError(28, "No space left on device")
    result = map_error("transcribe", err)
    assert "Disk full" in result


def test_unknown_stage_passthrough():
    err = ValueError("some error")
    result = map_error("unknown_stage", err)
    assert result == "some error"
