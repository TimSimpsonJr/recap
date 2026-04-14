"""Recording lifecycle state machine."""
from __future__ import annotations

from enum import Enum
from typing import Callable


class RecorderState(Enum):
    """States for the recording lifecycle."""

    IDLE = "idle"
    ARMED = "armed"
    DETECTED = "detected"
    RECORDING = "recording"
    PROCESSING = "processing"


class InvalidTransition(Exception):
    """Raised when an illegal state transition is attempted."""


class RecorderStateMachine:
    """Manages recording lifecycle transitions.

    Valid transitions:
        IDLE -> ARMED (arm)
        IDLE -> DETECTED (detected)
        IDLE -> RECORDING (start_recording)
        ARMED -> IDLE (disarm)
        ARMED -> DETECTED (detected)
        DETECTED -> RECORDING (start_recording)
        DETECTED -> IDLE (decline)
        RECORDING -> PROCESSING (stop_recording)
        PROCESSING -> IDLE (processing_complete)
    """

    def __init__(
        self,
        on_state_change: Callable[[RecorderState, RecorderState], None] | None = None,
    ) -> None:
        self._state = RecorderState.IDLE
        self._current_org: str | None = None
        self._on_state_change = on_state_change

    @property
    def state(self) -> RecorderState:
        """Current state (read-only)."""
        return self._state

    @property
    def current_org(self) -> str | None:
        """Which org this recording is for, or None when IDLE."""
        return self._current_org

    def set_on_state_change(
        self,
        callback: Callable[[RecorderState, RecorderState], None] | None,
    ) -> None:
        """Update the state-change callback without replacing the state machine."""
        self._on_state_change = callback

    def _transition(self, new_state: RecorderState) -> None:
        old = self._state
        self._state = new_state
        if self._on_state_change is not None:
            self._on_state_change(old, new_state)

    def _require(self, *allowed: RecorderState, action: str) -> None:
        if self._state not in allowed:
            raise InvalidTransition(
                f"Cannot {action} from {self._state.value}"
            )

    def start_recording(self, org: str) -> None:
        """IDLE -> RECORDING or DETECTED -> RECORDING."""
        self._require(RecorderState.IDLE, RecorderState.DETECTED, action="start_recording")
        self._current_org = org
        self._transition(RecorderState.RECORDING)

    def stop_recording(self) -> None:
        """RECORDING -> PROCESSING."""
        self._require(RecorderState.RECORDING, action="stop_recording")
        self._transition(RecorderState.PROCESSING)

    def processing_complete(self) -> None:
        """PROCESSING -> IDLE. Clears current_org."""
        self._require(RecorderState.PROCESSING, action="processing_complete")
        self._current_org = None
        self._transition(RecorderState.IDLE)

    def arm(self, org: str) -> None:
        """IDLE -> ARMED. Sets current_org for the expected meeting."""
        self._require(RecorderState.IDLE, action="arm")
        self._current_org = org
        self._transition(RecorderState.ARMED)

    def disarm(self) -> None:
        """ARMED -> IDLE. Clears current_org."""
        self._require(RecorderState.ARMED, action="disarm")
        self._current_org = None
        self._transition(RecorderState.IDLE)

    def detected(self, org: str) -> None:
        """ARMED -> DETECTED or IDLE -> DETECTED. Sets current_org."""
        self._require(RecorderState.ARMED, RecorderState.IDLE, action="detected")
        self._current_org = org
        self._transition(RecorderState.DETECTED)

    def decline(self) -> None:
        """DETECTED -> IDLE. Clears current_org."""
        self._require(RecorderState.DETECTED, action="decline")
        self._current_org = None
        self._transition(RecorderState.IDLE)

    def reset(self) -> None:
        """Return to IDLE from any non-idle state, clearing current_org."""
        if self._state == RecorderState.IDLE:
            self._current_org = None
            return
        self._current_org = None
        self._transition(RecorderState.IDLE)
