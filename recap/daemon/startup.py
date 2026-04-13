"""Startup validation for the Recap daemon.

Checks system requirements (vault path, GPU, audio devices, keyring)
before daemon launch and reports which checks passed or failed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger("recap.startup")


@dataclass
class StartupCheck:
    """Result of a single startup validation check."""

    name: str
    passed: bool
    message: str
    fatal: bool


@dataclass
class StartupResult:
    """Aggregated result of all startup validation checks."""

    checks: list[StartupCheck] = field(default_factory=list)

    @property
    def can_start(self) -> bool:
        """True if no fatal checks failed."""
        return all(c.passed for c in self.checks if c.fatal)

    @property
    def warnings(self) -> list[StartupCheck]:
        """Non-fatal checks that failed."""
        return [c for c in self.checks if not c.fatal and not c.passed]


def _check_cuda() -> bool:
    """Check if CUDA is available via torch."""
    try:
        import torch  # noqa: F811

        return torch.cuda.is_available()
    except Exception as e:
        logger.warning("Startup check failed: %s", e, exc_info=True)
        return False


def _check_audio_devices() -> bool:
    """Check if audio devices can be enumerated via PyAudioWPatch."""
    try:
        import pyaudiowpatch as pyaudio  # noqa: F811

        p = pyaudio.PyAudio()
        try:
            count = p.get_device_count()
            return count > 0
        finally:
            p.terminate()
    except Exception as e:
        logger.warning("Startup check failed: %s", e, exc_info=True)
        return False


def _check_keyring() -> bool:
    """Check if keyring backend is functional."""
    try:
        import keyring  # noqa: F811

        keyring.get_password("recap-test", "test")
        return True
    except Exception as e:
        logger.warning("Startup check failed: %s", e, exc_info=True)
        return False


def validate_startup(
    vault_path: Path,
    check_gpu: bool = True,
) -> StartupResult:
    """Run all startup validation checks.

    Args:
        vault_path: Path to the Obsidian vault directory.
        check_gpu: Whether to check for CUDA/GPU availability.

    Returns:
        StartupResult with all check outcomes.
    """
    result = StartupResult()

    # Vault path check (fatal)
    if vault_path.is_dir():
        result.checks.append(
            StartupCheck(
                name="vault_path",
                passed=True,
                message=f"Vault path exists: {vault_path}",
                fatal=True,
            )
        )
    else:
        result.checks.append(
            StartupCheck(
                name="vault_path",
                passed=False,
                message=f"Vault path not found: {vault_path}",
                fatal=True,
            )
        )

    # GPU check (non-fatal)
    if check_gpu:
        gpu_ok = _check_cuda()
        result.checks.append(
            StartupCheck(
                name="gpu",
                passed=gpu_ok,
                message="CUDA available" if gpu_ok else "CUDA not available",
                fatal=False,
            )
        )

    # Audio devices check (non-fatal)
    audio_ok = _check_audio_devices()
    result.checks.append(
        StartupCheck(
            name="audio_devices",
            passed=audio_ok,
            message="Audio devices found" if audio_ok else "No audio devices found",
            fatal=False,
        )
    )

    # Keyring check (non-fatal)
    keyring_ok = _check_keyring()
    result.checks.append(
        StartupCheck(
            name="keyring",
            passed=keyring_ok,
            message="Keyring accessible" if keyring_ok else "Keyring not accessible",
            fatal=False,
        )
    )

    return result
