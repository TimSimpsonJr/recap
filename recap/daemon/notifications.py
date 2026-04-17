"""Windows toast notifications for the daemon.

In addition to showing an OS toast, ``notify()`` optionally appends the
notification to the daemon event journal (design doc §0.4) so the Obsidian
plugin's ``NotificationHistory.ts`` can render history as a thin view over
daemon data -- the plugin itself never writes to the journal.
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from recap.daemon.events import EventJournal

logger = logging.getLogger("recap.notifications")


def notify(
    title: str,
    message: str,
    *,
    journal: Optional["EventJournal"] = None,
    level: str = "info",
    event: str = "notification",
) -> None:
    """Send a Windows toast notification. Never crashes the daemon.

    Parameters
    ----------
    title
        Short toast title (becomes ``payload.title`` in the journal entry).
    message
        Toast body text (becomes the journal entry ``message``).
    journal
        Optional :class:`EventJournal` to append this notification to. When
        ``None`` (the default) the journal side-effect is skipped, which
        keeps callers that don't have a daemon in scope (tests, one-off
        scripts, subservices not wired through ``daemon``) working.
    level
        Journal level -- ``info``, ``warning``, or ``error``. Defaults to
        ``info``. Ignored when ``journal`` is ``None``.
    event
        Journal event slug. Defaults to ``notification`` -- a generic
        bucket. Pass a more specific slug (e.g. ``pipeline_failed``) when
        the caller knows the semantic category.
    """
    try:
        from plyer import notification

        # Windows ``NOTIFYICONDATAW.szInfo`` caps the balloon body at 256
        # characters. plyer's background ``balloon_tip`` thread raises
        # ``ValueError: string too long`` when handed more, which
        # surfaces as noisy stderr tracebacks even though the daemon
        # keeps running. Truncate defensively (the full message is
        # preserved in the journal entry below so API consumers still
        # get the complete text).
        toast_message = message
        if len(toast_message) > 250:
            toast_message = toast_message[:247] + "..."
        notification.notify(
            title=title,
            message=toast_message,
            app_name="Recap",
            timeout=10,
        )
    except Exception as e:
        logger.warning("Failed to send notification: %s", e)

    if journal is not None:
        try:
            journal.append(level, event, message, payload={"title": title})
        except Exception:
            # A broken journal must not crash the notification path.
            logger.exception("Failed to journal notification")
