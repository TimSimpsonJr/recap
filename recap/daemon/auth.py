"""Auth token generation and validation for daemon-plugin communication."""

import hmac
import secrets
from pathlib import Path


def ensure_auth_token(path: Path) -> str:
    """Return the auth token at *path*, creating it if it doesn't exist.

    If the file is missing a new ``secrets.token_urlsafe(32)`` value is
    generated, written to *path*, and returned.  If it already exists the
    stored value is read and returned as-is.
    """
    if path.exists():
        return path.read_text().strip()

    token = secrets.token_urlsafe(32)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token)
    return token


def validate_token(token: str, token_path: Path) -> bool:
    """Constant-time comparison of *token* against the value stored in *token_path*."""
    expected = token_path.read_text().strip()
    return hmac.compare_digest(token, expected)
