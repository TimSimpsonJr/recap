"""Map raw pipeline exceptions to actionable error messages."""
from __future__ import annotations

import errno


def map_error(stage: str, error: Exception, **context: str) -> str:
    """Convert a pipeline exception to an actionable message.

    Checks ``str(error).lower()`` against known patterns per stage and returns
    a user-facing message that references the relevant Settings section.
    Falls through to ``str(error)`` for unknown errors.
    """
    msg = str(error).lower()

    # --- Cross-stage errors ---
    if isinstance(error, OSError) and getattr(error, "errno", None) == errno.ENOSPC:
        return "Disk full \u2014 free space and retry"

    # --- Per-stage mappings ---
    if stage == "transcribe":
        return _map_transcribe(error, msg)
    if stage == "diarize":
        return _map_diarize(error, msg)
    if stage == "analyze":
        return _map_analyze(error, msg, context)
    if stage == "export":
        return _map_export(error, msg, context)
    if stage == "convert":
        return _map_convert(error, msg)

    return str(error)


def _map_transcribe(error: Exception, msg: str) -> str:
    if "cuda" in msg and ("not available" in msg or "no cuda" in msg):
        return (
            "CUDA not available \u2014 "
            "check GPU drivers or switch device to 'cpu' in Settings > Pipeline"
        )
    if "out of memory" in msg or "cuda out of memory" in msg:
        return (
            "GPU out of memory \u2014 "
            "try a smaller Parakeet model in Settings > Pipeline"
        )
    if "download" in msg or "connection" in msg or "resolve" in msg:
        return (
            "Failed to download Parakeet model \u2014 "
            "check your internet connection"
        )
    if isinstance(error, (FileNotFoundError, OSError)):
        return "Audio file not found or unreadable \u2014 recording may be incomplete"
    return str(error)


def _map_diarize(error: Exception, msg: str) -> str:
    if "cuda" in msg and ("not available" in msg or "no cuda" in msg):
        return (
            "CUDA not available \u2014 "
            "check GPU drivers or switch device to 'cpu' in Settings > Pipeline"
        )
    if "out of memory" in msg or "cuda out of memory" in msg:
        return (
            "GPU out of memory during diarization \u2014 "
            "close other GPU applications and retry"
        )
    if "download" in msg or "connection" in msg or "resolve" in msg:
        return (
            "Failed to download NeMo diarization model \u2014 "
            "check your internet connection"
        )
    if isinstance(error, (FileNotFoundError, OSError)):
        return "Audio file not found or unreadable \u2014 recording may be incomplete"
    return str(error)


def _map_analyze(error: Exception, msg: str, context: dict[str, str]) -> str:
    if isinstance(error, FileNotFoundError) and ("prompt" in msg or "template" in msg):
        return "Prompt template not found \u2014 check Recap installation"
    if isinstance(error, FileNotFoundError) or "not found" in msg:
        command = context.get("command", "claude")
        return (
            f"Claude CLI not found at '{command}' \u2014 "
            "update the path in Settings > Claude"
        )
    if "rate" in msg and "limit" in msg:
        return "Claude rate limited \u2014 wait a few minutes and retry"
    if isinstance(error, RuntimeError) and "failed after" in msg:
        last = context.get("last_error", "")
        if "auth" in last.lower():
            return (
                "Claude analysis failed \u2014 "
                "check Claude CLI is authenticated (run 'claude' in a terminal)"
            )
        return (
            "Claude returned unexpected output \u2014 "
            "retry (transient) or check prompt template"
        )
    return str(error)


def _map_export(error: Exception, msg: str, context: dict[str, str]) -> str:
    if isinstance(error, FileNotFoundError) or "not found" in msg:
        return "Vault path does not exist \u2014 update it in Settings > Vault"
    if isinstance(error, PermissionError) or "permission" in msg:
        vault_path = context.get("vault_path", "unknown")
        return (
            f"Cannot write to vault \u2014 check folder permissions for {vault_path}"
        )
    return str(error)


def _map_convert(error: Exception, msg: str) -> str:
    if ("ffmpeg" in msg or "ffprobe" in msg) and "not found" in msg:
        return "ffmpeg not found \u2014 ensure ffmpeg is installed and on system PATH"
    if isinstance(error, FileNotFoundError):
        return "Recording file not found \u2014 it may have been moved or deleted"
    if "permission" in msg:
        return "Cannot write converted audio \u2014 check folder permissions"
    return str(error)
