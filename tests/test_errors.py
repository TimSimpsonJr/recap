"""Tests for recap.errors.map_error."""
from recap.errors import map_error


def test_hf_auth_error():
    err = Exception("401 Unauthorized: invalid token")
    result = map_error("transcribe", err)
    assert "HuggingFace authentication" in result
    assert "Settings > WhisperX" in result


def test_cuda_unavailable():
    err = RuntimeError("CUDA not available")
    result = map_error("transcribe", err)
    assert "CUDA not available" in result


def test_gpu_oom():
    err = RuntimeError("CUDA out of memory")
    result = map_error("transcribe", err)
    assert "GPU out of memory" in result
    assert "smaller model" in result


def test_claude_not_found():
    err = FileNotFoundError("No such file: claude")
    result = map_error("analyze", err, command="/usr/bin/claude")
    assert "Claude CLI not found" in result


def test_vault_missing():
    err = FileNotFoundError("Path not found")
    result = map_error("export", err, vault_path="/foo/vault")
    assert "Vault path does not exist" in result


def test_ffmpeg_not_found():
    err = RuntimeError("ffmpeg not found in PATH")
    result = map_error("frames", err)
    assert "ffmpeg not found" in result


def test_todoist_auth():
    err = Exception("401 Unauthorized")
    result = map_error("todoist", err)
    assert "Todoist authentication" in result


def test_unknown_error_passthrough():
    err = ValueError("something unexpected")
    result = map_error("transcribe", err)
    assert result == "something unexpected"


def test_disk_full():
    err = OSError(28, "No space left on device")
    result = map_error("transcribe", err)
    assert "Disk full" in result
