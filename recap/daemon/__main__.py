"""Entry point: python -m recap.daemon <config-path>"""
from __future__ import annotations

import logging
import os
import pathlib
import signal
import sys
import threading

from aiohttp import web

from recap.daemon.auth import ensure_auth_token
from recap.daemon.config import load_daemon_config
from recap.daemon.logging_setup import setup_logging
from recap.daemon.notifications import notify
from recap.daemon.server import create_app
from recap.daemon.startup import validate_startup
from recap.daemon.tray import RecapTray

logger = logging.getLogger("recap.daemon")


def main() -> None:
    # Parse config path from args
    if len(sys.argv) < 2:
        print("Usage: python -m recap.daemon <config-path>")
        sys.exit(1)

    config_path = pathlib.Path(sys.argv[1])
    if not config_path.exists():
        print(f"Config file not found: {config_path}")
        sys.exit(1)

    # Load config
    try:
        config = load_daemon_config(config_path)
    except (ValueError, FileNotFoundError) as e:
        print(f"Config error: {e}")
        sys.exit(1)

    # Setup logging
    log_path = config.vault_path / config.logging.path
    setup_logging(log_path, config.logging.retention_days)
    logger.info("Recap daemon starting")

    # Startup validation
    result = validate_startup(vault_path=config.vault_path, check_gpu=True)
    for check in result.warnings:
        logger.warning("Startup check: %s -- %s", check.name, check.message)
        notify("Recap", check.message)

    if not result.can_start:
        for check in result.checks:
            if check.fatal and not check.passed:
                logger.error(
                    "Fatal startup check: %s -- %s", check.name, check.message,
                )
                notify("Recap -- Cannot Start", check.message)
        sys.exit(1)

    logger.info("Startup validation passed")

    # Auth token
    recap_dir = config.vault_path / "_Recap" / ".recap"
    recap_dir.mkdir(parents=True, exist_ok=True)
    auth_token_path = recap_dir / "auth-token"
    auth_token = ensure_auth_token(auth_token_path)
    logger.info("Auth token ready")

    # Create HTTP app
    app = create_app(auth_token=auth_token)

    # Setup tray
    org_names = [org.name for org in config.orgs]

    def on_quit() -> None:
        logger.info("Quit requested from tray")
        os.kill(os.getpid(), signal.SIGINT)

    tray = RecapTray(
        orgs=org_names,
        on_start_recording=lambda org: logger.info(
            "Start recording requested: %s (not yet implemented)", org,
        ),
        on_stop_recording=lambda: logger.info(
            "Stop recording requested (not yet implemented)",
        ),
        on_quit=on_quit,
    )

    # Start tray in background thread
    tray_thread = threading.Thread(target=tray.run, daemon=True, name="recap-tray")
    tray_thread.start()
    logger.info("System tray started")

    # Run HTTP server (blocking)
    logger.info("Starting HTTP server on port %d", config.daemon_ports.plugin_port)
    web.run_app(
        app,
        host="127.0.0.1",
        port=config.daemon_ports.plugin_port,
        print=lambda msg: logger.info(msg),
    )


if __name__ == "__main__":
    main()
