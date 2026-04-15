"""Pairing window for extension auth (design §0.5).

The pairing window is a short-lived, loopback-only, one-shot token issuer.
The tray menu item ``"Pair browser extension..."`` calls :meth:`open` on
this window. While open, the daemon's ``/bootstrap/token`` endpoint is
enabled; the first successful loopback GET against it calls
:meth:`consume`, which closes the window and returns the pairing token.

Safety valves:

- Window auto-closes after ``timeout_seconds`` with no consumer (via
  :meth:`check_timeout`, polled by ``Daemon.start()``).
- Non-loopback requesters are rejected without closing the window so a
  legitimate loopback caller can still succeed.
- Every lifecycle transition (open, issued, failed non-loopback,
  timeout) is journaled.

All methods are thread-safe: :meth:`open`, :meth:`consume`, and
:meth:`check_timeout` take the same internal lock, so tray-thread
opens race cleanly with event-loop consumes and the timeout poller.
"""
from __future__ import annotations

import secrets
import threading
import time
from typing import Optional

_LOOPBACK_IPS = {"127.0.0.1", "::1"}


def _now() -> float:
    """Return the current monotonic clock reading.

    Factored out so tests can monkey-patch a controllable clock.
    """
    return time.monotonic()


class PairingWindow:
    """One-shot, loopback-only, journaled pairing token issuer."""

    def __init__(self, *, journal, timeout_seconds: float = 60.0) -> None:
        self._journal = journal
        self._timeout = timeout_seconds
        self._lock = threading.Lock()
        self._is_open = False
        self._token: Optional[str] = None
        self._opened_at: Optional[float] = None

    @property
    def is_open(self) -> bool:
        """Whether the window is currently accepting a consumer."""
        with self._lock:
            return self._is_open

    @property
    def current_token(self) -> Optional[str]:
        """The active pairing token, or ``None`` when the window is closed."""
        with self._lock:
            return self._token if self._is_open else None

    def open(self) -> None:
        """Open the window and mint a fresh pairing token.

        A second ``open()`` while already open is a no-op (the existing
        token stays valid). The window is closed again by :meth:`consume`
        or :meth:`check_timeout`.
        """
        with self._lock:
            if self._is_open:
                return
            self._token = secrets.token_urlsafe(32)
            self._is_open = True
            self._opened_at = _now()
        self._journal.append("info", "pairing_opened", "Pairing window opened")

    def consume(self, *, requester_ip: str) -> str:
        """Consume the window's token and close it.

        Raises :class:`RuntimeError` if the window is closed, and
        :class:`PermissionError` if the requester is not loopback. In
        the non-loopback case the window stays open so a legitimate
        loopback caller can still succeed.
        """
        non_loopback = False
        token: Optional[str] = None
        with self._lock:
            if not self._is_open:
                raise RuntimeError("pairing window closed")
            if requester_ip not in _LOOPBACK_IPS:
                # Do NOT close the window -- a legitimate loopback caller
                # can still succeed. Defer journaling + raising to outside
                # the lock so we don't hold it across I/O.
                non_loopback = True
            else:
                token = self._token
                assert token is not None
                self._is_open = False
                self._token = None
                self._opened_at = None
        if non_loopback:
            self._journal.append(
                "warning",
                "pairing_failed_non_loopback",
                f"Non-loopback pairing attempt from {requester_ip}",
                payload={"requester_ip": requester_ip},
            )
            raise PermissionError(f"non-loopback requester {requester_ip}")
        self._journal.append(
            "info",
            "pairing_token_issued",
            "Pairing token issued",
            payload={"requester_ip": requester_ip},
        )
        assert token is not None
        return token

    def check_timeout(self) -> None:
        """Close the window if it has been open past ``timeout_seconds``.

        Safe to call while the window is closed (no-op). The daemon's
        periodic timeout loop calls this every ~5s.
        """
        with self._lock:
            if not self._is_open or self._opened_at is None:
                return
            elapsed = _now() - self._opened_at
            if elapsed < self._timeout:
                return
            self._is_open = False
            self._token = None
            self._opened_at = None
        self._journal.append(
            "warning",
            "pairing_closed_timeout",
            "Pairing window expired with no consumer",
        )
