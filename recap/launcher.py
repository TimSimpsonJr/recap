"""Supervisor watchdog for the Recap daemon.

Launches ``recap.daemon`` as a child process and restarts it when the
daemon exits with :data:`~recap.daemon.exit_codes.EXIT_RESTART_REQUESTED`
(42). Any other non-zero exit is treated as fatal: the launcher logs
loudly and exits with the same code instead of crash-looping.

Why this exists
---------------
The daemon itself cannot meaningfully ``os.execv`` into a new copy of
itself on Windows: subprocesses, the tray icon, and open file handles
make self-reexec unreliable. A thin external supervisor is the
production-shaped alternative to baking restart logic into the daemon
process.

Usage::

    uv run python -m recap.launcher <config-path>

All arguments after ``recap.launcher`` are forwarded verbatim to the
daemon child, so everything that works with ``python -m recap.daemon``
also works here (including the positional ``config`` path).

Environment contract
--------------------
The launcher sets ``RECAP_MANAGED=1`` in the child's environment.
The daemon reads this at startup and advertises ``can_restart: true``
via ``/api/status`` so the plugin can enable its Restart button.
Standalone daemons (launched without the wrapper) never see
``RECAP_MANAGED`` and therefore report ``can_restart: false``.

Logging
-------
The launcher writes its own log to ``RECAP_LAUNCHER_LOG`` (default:
``<cwd>/launcher.log``). Only restart/shutdown markers and child exit
codes go here -- the daemon keeps writing its normal structured log.
This avoids the two-partial-sources-of-truth problem where child
stdout and daemon log both claim to be the record of what happened.
"""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import time
from pathlib import Path

from recap.daemon.exit_codes import EXIT_RESTART_REQUESTED, EXIT_STOP

logger = logging.getLogger("recap.launcher")

# Crash-loop detector. Only *fast* consecutive restarts count: if the
# daemon runs longer than ``_HEALTHY_RUN_SECONDS`` before the next
# restart request, the counter resets to 0. This lets a user hit the
# plugin's Restart button dozens of times over the daemon's lifetime
# without the launcher eventually giving up, while still catching the
# failure mode where a bug triggers ``restart_requested=True`` on
# every boot (the daemon never lives long enough to reset the counter).
_MAX_RESTARTS = 10
_HEALTHY_RUN_SECONDS = 30.0


def _configure_logging() -> Path:
    """Attach a file handler to ``recap.launcher`` at ``RECAP_LAUNCHER_LOG``.

    Returns the log path so the caller can include it in user-facing
    error messages.
    """
    log_path = Path(os.environ.get("RECAP_LAUNCHER_LOG", "launcher.log"))
    log_path.parent.mkdir(parents=True, exist_ok=True)

    # Idempotent setup: tests call ``run()`` multiple times in the same
    # process, and re-adding a handler every call duplicates log lines.
    already = any(
        isinstance(h, logging.FileHandler)
        and Path(h.baseFilename) == log_path.resolve()
        for h in logger.handlers
    )
    if not already:
        handler = logging.FileHandler(log_path, encoding="utf-8")
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(message)s"),
        )
        logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    return log_path


def _spawn_daemon(extra_args: list[str]) -> subprocess.Popen:
    """Start one daemon child process with ``RECAP_MANAGED=1`` in its env.

    stdout and stderr are inherited so users running the launcher from
    a terminal see daemon output in place; the launcher's own file log
    only records supervise events."""
    argv = [sys.executable, "-m", "recap.daemon", *extra_args]
    env = {**os.environ, "RECAP_MANAGED": "1"}
    return subprocess.Popen(
        argv,
        env=env,
        stdout=None,
        stderr=None,
    )


def run(extra_args: list[str] | None = None) -> int:
    """Run the supervise loop. Returns the launcher's final exit code.

    Loop behavior:

    - ``EXIT_STOP`` (0): stop supervising, exit 0.
    - ``EXIT_RESTART_REQUESTED`` (42): spawn a fresh child. If the
      previous child ran at least ``_HEALTHY_RUN_SECONDS``, reset the
      consecutive-restart counter; otherwise increment it. Exceeding
      ``_MAX_RESTARTS`` consecutive *fast* restarts is treated as a
      crash loop and the launcher bails.
    - Any other code: log loudly and exit with the same code.
    """
    _configure_logging()
    args = list(extra_args or [])
    fast_restarts = 0
    attempt = 0
    while True:
        attempt += 1
        logger.info("daemon child starting (attempt %d)", attempt)
        spawn_time = time.monotonic()
        proc = _spawn_daemon(args)
        code = proc.wait()
        run_duration = time.monotonic() - spawn_time
        logger.info(
            "daemon child exited with code %d after %.1fs",
            code, run_duration,
        )

        if code == EXIT_STOP:
            return EXIT_STOP
        if code == EXIT_RESTART_REQUESTED:
            if run_duration >= _HEALTHY_RUN_SECONDS:
                # Child ran long enough to be considered healthy; any
                # prior crash-loop suspicion is cleared.
                fast_restarts = 0
            else:
                fast_restarts += 1
            if fast_restarts > _MAX_RESTARTS:
                logger.error(
                    "daemon restarted %d times in under %.0fs each; "
                    "giving up to avoid a crash loop",
                    fast_restarts, _HEALTHY_RUN_SECONDS,
                )
                return code
            continue
        # Any other code: log loudly and exit with the same code so the
        # user (or systemd / Windows service wrapper) sees the failure.
        logger.error(
            "daemon child exited with unexpected code %d; launcher stopping",
            code,
        )
        return code


def main(argv: list[str] | None = None) -> None:
    """CLI entry: forward everything after ``recap.launcher`` to the daemon."""
    args = sys.argv[1:] if argv is None else argv
    sys.exit(run(extra_args=args))


if __name__ == "__main__":
    main()
