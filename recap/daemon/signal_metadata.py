"""Helper to construct RecordingMetadata for Signal-call recordings.

Extracted from daemon/__main__.py so the construction logic can be tested
in isolation without importing the daemon entry point (which pulls in
pystray and other GUI dependencies).
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from recap.artifacts import RecordingMetadata
from recap.models import Participant


def build_signal_metadata(
    result: dict[str, Any],
    meeting_window: Any,
    enriched_metadata: dict[str, Any],
) -> RecordingMetadata:
    """Build RecordingMetadata from the Signal popup result and enrichment.

    Ensures the user's backend choice (Claude vs. Ollama "Local only") from
    the popup flows into `RecordingMetadata.llm_backend` so the runtime
    config picks it up. See Codex Phase 1 review finding #1.
    """
    return RecordingMetadata(
        org=result["org"],
        note_path="",
        title=enriched_metadata.get("title", meeting_window.title),
        date=datetime.now().date().isoformat(),
        participants=[
            Participant(name=name)
            for name in enriched_metadata.get("participants", [])
        ],
        platform=enriched_metadata.get("platform", meeting_window.platform),
        llm_backend=result["backend"],
    )
