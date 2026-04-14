"""Keyring-backed credential storage for OAuth tokens."""
from __future__ import annotations

import logging
from typing import Any

try:
    import keyring  # type: ignore[import-not-found]
except Exception:  # pragma: no cover - exercised in dependency-light environments
    keyring = None  # type: ignore[assignment]

logger = logging.getLogger("recap.credentials")

SERVICE_PREFIX = "recap"


def _require_keyring() -> Any:
    global keyring
    if keyring is None:
        try:
            import keyring as imported_keyring  # type: ignore[import-not-found]
        except Exception as exc:  # pragma: no cover - depends on local env
            raise RuntimeError(
                "keyring is required for credential storage. Install the daemon extras.",
            ) from exc
        keyring = imported_keyring
    return keyring


def store_credential(provider: str, key: str, value: str) -> None:
    """Store a credential in the OS keyring."""
    kr = _require_keyring()
    try:
        kr.set_password(f"{SERVICE_PREFIX}-{provider}", key, value)
    except Exception as e:
        logger.error("Failed to store credential %s/%s: %s", provider, key, e)
        raise


def get_credential(provider: str, key: str) -> str | None:
    """Retrieve a credential from the OS keyring. Returns None if not found."""
    kr = _require_keyring()
    try:
        return kr.get_password(f"{SERVICE_PREFIX}-{provider}", key)
    except Exception as e:
        logger.error("Failed to get credential %s/%s: %s", provider, key, e)
        return None


def delete_credential(provider: str, key: str) -> None:
    """Delete a credential from the OS keyring."""
    kr = _require_keyring()
    try:
        kr.delete_password(f"{SERVICE_PREFIX}-{provider}", key)
    except kr.errors.PasswordDeleteError:
        pass  # already deleted
    except Exception as e:
        logger.error("Failed to delete credential %s/%s: %s", provider, key, e)
        raise


def has_credential(provider: str, key: str) -> bool:
    """Check if a credential exists."""
    return get_credential(provider, key) is not None
