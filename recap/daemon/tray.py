"""System tray icon for the Recap daemon."""
from __future__ import annotations

import logging
from collections.abc import Callable

import pystray
from PIL import Image, ImageDraw

logger = logging.getLogger("recap.tray")

# Icon colors by state
_COLORS = {
    "idle": "#22c55e",       # green
    "recording": "#ef4444",  # red
    "processing": "#eab308", # yellow
}

_ICON_SIZE = 64


def _make_icon(color: str) -> Image.Image:
    """Generate a solid colored circle on a transparent background."""
    img = Image.new("RGBA", (_ICON_SIZE, _ICON_SIZE), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([4, 4, _ICON_SIZE - 4, _ICON_SIZE - 4], fill=color)
    return img


class RecapTray:
    """System tray icon with recording controls.

    Parameters
    ----------
    orgs:
        Organisation names shown in the "Start Recording" submenu.
    on_start_recording:
        Called with the chosen org name when the user starts recording.
    on_stop_recording:
        Called when the user stops recording.
    on_pair_extension:
        Called when the user clicks "Pair browser extension...". Opens
        the :class:`PairingWindow` so the extension can fetch
        ``/bootstrap/token`` (design §0.5).
    on_quit:
        Called when the user clicks Quit.
    """

    def __init__(
        self,
        orgs: list[str],
        on_start_recording: Callable[[str], None] | None = None,
        on_stop_recording: Callable[[], None] | None = None,
        on_pair_extension: Callable[[], None] | None = None,
        on_quit: Callable[[], None] | None = None,
    ) -> None:
        self._orgs = orgs
        self._on_start_recording = on_start_recording
        self._on_stop_recording = on_stop_recording
        self._on_pair_extension = on_pair_extension
        self._on_quit = on_quit

        self._state = "idle"
        self._current_org = ""
        self._icon: pystray.Icon | None = None

    # -- menu helpers --------------------------------------------------------

    def _status_text(self) -> str:
        if self._state == "recording":
            return f"Status: Recording ({self._current_org})"
        if self._state == "processing":
            return "Status: Processing..."
        return "Status: Idle"

    def _is_recording(self) -> bool:
        return self._state == "recording"

    def _build_menu(self) -> pystray.Menu:
        return pystray.Menu(
            pystray.MenuItem(self._status_text(), None, enabled=False),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Start Recording",
                pystray.Menu(
                    *(
                        pystray.MenuItem(
                            org,
                            self._make_start_handler(org),
                        )
                        for org in self._orgs
                    )
                ),
            ),
            pystray.MenuItem(
                "Stop Recording",
                self._handle_stop,
                enabled=self._is_recording(),
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem(
                "Pair browser extension...",
                self._handle_pair_extension,
            ),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("Quit", self._handle_quit),
        )

    # -- callbacks -----------------------------------------------------------

    def _make_start_handler(self, org: str) -> Callable[..., None]:
        def handler(icon: pystray.Icon, item: pystray.MenuItem) -> None:
            logger.info("Start recording requested for org: %s", org)
            if self._on_start_recording:
                self._on_start_recording(org)

        return handler

    def _handle_stop(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("Stop recording requested")
        if self._on_stop_recording:
            self._on_stop_recording()

    def _handle_pair_extension(
        self, icon: pystray.Icon, item: pystray.MenuItem,
    ) -> None:
        logger.info("Pair browser extension requested from tray")
        if self._on_pair_extension:
            self._on_pair_extension()

    def _handle_quit(self, icon: pystray.Icon, item: pystray.MenuItem) -> None:
        logger.info("Quit requested from tray")
        if self._on_quit:
            self._on_quit()
        self.stop()

    # -- public API ----------------------------------------------------------

    def update_state(self, state: str, org: str = "") -> None:
        """Update icon color and menu to reflect the current daemon state.

        Parameters
        ----------
        state:
            One of ``"idle"``, ``"recording"``, ``"processing"``.
        org:
            Organisation name (only meaningful when *state* is ``"recording"``).
        """
        self._state = state
        self._current_org = org

        if self._icon is not None:
            color = _COLORS.get(state, _COLORS["idle"])
            self._icon.icon = _make_icon(color)
            self._icon.menu = self._build_menu()
            self._icon.update_menu()

    def run(self) -> None:
        """Start the tray icon. Blocks until :meth:`stop` is called."""
        self._icon = pystray.Icon(
            name="recap",
            icon=_make_icon(_COLORS["idle"]),
            title="Recap",
            menu=self._build_menu(),
        )
        self._icon.run()

    def stop(self) -> None:
        """Stop the tray icon and unblock :meth:`run`."""
        if self._icon is not None:
            self._icon.stop()
