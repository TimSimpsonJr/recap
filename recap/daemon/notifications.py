"""Windows toast notifications for the daemon."""
from __future__ import annotations

import logging

logger = logging.getLogger("recap.notifications")


def notify(title: str, message: str) -> None:
    """Send a Windows toast notification. Never crashes the daemon."""
    try:
        from plyer import notification

        notification.notify(
            title=title,
            message=message,
            app_name="Recap",
            timeout=10,
        )
    except Exception as e:
        logger.warning("Failed to send notification: %s", e)
