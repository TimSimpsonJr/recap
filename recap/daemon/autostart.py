"""Windows auto-start management (stub).

Provides the interface for registering/unregistering the daemon
to run on Windows login via Task Scheduler. The actual schtasks
commands are not implemented yet --- this module provides the
structure so the plugin settings UI can query and toggle the state.

TODO: Implement actual Task Scheduler registration during
installation/setup phase.
"""

import logging
import pathlib

logger = logging.getLogger("recap.autostart")


def install_autostart(daemon_exe_path: pathlib.Path, config_path: pathlib.Path) -> bool:
    """Register daemon to run on user login via Task Scheduler.

    Returns True on success, False on failure.

    NOT YET IMPLEMENTED --- returns False with a log message.
    """
    logger.warning(
        "Auto-start registration not yet implemented. "
        "To run the daemon on login, manually create a Task Scheduler entry for: "
        "%s %s",
        daemon_exe_path,
        config_path,
    )
    return False


def remove_autostart() -> bool:
    """Remove daemon from Task Scheduler.

    Returns True on success, False on failure.

    NOT YET IMPLEMENTED --- returns False with a log message.
    """
    logger.warning("Auto-start removal not yet implemented.")
    return False


def is_autostart_enabled() -> bool:
    """Check if daemon is registered in Task Scheduler.

    NOT YET IMPLEMENTED --- always returns False.
    """
    return False
