"""Keyring-backed credential storage for OAuth tokens."""
import logging
import keyring

logger = logging.getLogger("recap.credentials")

SERVICE_PREFIX = "recap"


def store_credential(provider: str, key: str, value: str) -> None:
    """Store a credential in the OS keyring."""
    try:
        keyring.set_password(f"{SERVICE_PREFIX}-{provider}", key, value)
    except Exception as e:
        logger.error("Failed to store credential %s/%s: %s", provider, key, e)
        raise


def get_credential(provider: str, key: str) -> str | None:
    """Retrieve a credential from the OS keyring. Returns None if not found."""
    try:
        return keyring.get_password(f"{SERVICE_PREFIX}-{provider}", key)
    except Exception as e:
        logger.error("Failed to get credential %s/%s: %s", provider, key, e)
        return None


def delete_credential(provider: str, key: str) -> None:
    """Delete a credential from the OS keyring."""
    try:
        keyring.delete_password(f"{SERVICE_PREFIX}-{provider}", key)
    except keyring.errors.PasswordDeleteError:
        pass  # already deleted
    except Exception as e:
        logger.error("Failed to delete credential %s/%s: %s", provider, key, e)
        raise


def has_credential(provider: str, key: str) -> bool:
    """Check if a credential exists."""
    return get_credential(provider, key) is not None
