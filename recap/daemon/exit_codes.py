"""Well-known process exit codes shared by the daemon and launcher.

The launcher (``recap/launcher.py``) supervises the daemon as a child
process. When the daemon exits with ``EXIT_RESTART_REQUESTED`` the
launcher loops and spawns a fresh child; any other non-zero code is
treated as a fatal error (loud log, launcher exits with the same code).

These constants are shared so the restart handshake stays a named
contract instead of a magic number split between two modules.
"""
from __future__ import annotations

EXIT_STOP: int = 0
"""Normal shutdown. The launcher stops its supervise loop and exits 0."""

EXIT_RESTART_REQUESTED: int = 42
"""Shutdown-for-restart. The launcher spawns a fresh daemon child."""
