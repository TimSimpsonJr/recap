"""Well-known journal event types and sidecar warning codes for audio capture.

Shared between the recorder (which emits the events and persists warning
codes to the sidecar) and the pipeline export path (which reads warning
codes and renders them as note frontmatter + body callouts).
"""
from __future__ import annotations

# Journal event types (used as EventJournal category names).
EVT_AUDIO_NO_LOOPBACK_AT_START = "audio_capture_no_loopback_at_start"
"""Emitted once at recording start when WASAPI enumerates zero render endpoints."""

EVT_AUDIO_NO_SYSTEM_AUDIO = "audio_capture_no_system_audio"
"""Emitted once when the last PROBATION entry expires with no entry ever ACTIVE."""

EVT_AUDIO_ALL_LOOPBACKS_LOST = "audio_capture_all_loopbacks_lost"
"""Emitted when the count of ACTIVE entries transitions from non-zero to zero
(given at least one entry had ever been ACTIVE during the recording)."""

# Sidecar warning codes (persisted in RecordingMetadata.audio_warnings).
WARN_NO_SYSTEM_AUDIO_CAPTURED = "no-system-audio-captured"
"""Recorder never achieved ACTIVE loopback coverage. Scenarios A and B."""

WARN_SYSTEM_AUDIO_INTERRUPTED = "system-audio-interrupted"
"""Recorder had ACTIVE coverage at some point, then lost it. Scenario C."""
