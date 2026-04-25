"""Helpers for recording sidecar artifacts."""
from __future__ import annotations

import json
import os
import pathlib
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any

from recap.models import AnalysisResult, MeetingMetadata, Participant, TranscriptResult


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')


def safe_note_title(title: str) -> str:
    sanitized = _INVALID_FILENAME_CHARS.sub(" ", title).strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized or "Meeting"


def resolve_note_path(note_path_str: str, vault_path: pathlib.Path) -> pathlib.Path:
    """Resolve a stored note_path against the vault root.

    Accepts both absolute (legacy) and vault-relative (new) forms.
    """
    p = pathlib.Path(note_path_str)
    if p.is_absolute():
        return p
    return vault_path / p


def to_vault_relative(note_path: pathlib.Path, vault_path: pathlib.Path) -> str:
    """Convert an absolute path to a vault-relative string with forward slashes.

    Falls back to the path as-is if it lies outside *vault_path* (degraded mode).
    """
    try:
        return str(note_path.relative_to(vault_path)).replace("\\", "/")
    except ValueError:
        return str(note_path)


@dataclass
class RecordingMetadata:
    org: str
    note_path: str
    title: str
    date: str
    participants: list[Participant]
    platform: str
    calendar_source: str | None = None
    event_id: str | None = None
    meeting_link: str = ""
    llm_backend: str | None = None
    audio_warnings: list[str] = field(default_factory=list)
    system_audio_devices_seen: list[str] = field(default_factory=list)
    recording_started_at: datetime | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingMetadata:
        participants = [
            Participant(name=p["name"], email=p.get("email"))
            for p in data.get("participants", [])
        ]
        started_raw = data.get("recording_started_at")
        recording_started_at: datetime | None = (
            datetime.fromisoformat(started_raw) if started_raw else None
        )
        return cls(
            org=data["org"],
            note_path=data["note_path"],
            title=data["title"],
            date=data["date"],
            participants=participants,
            platform=data.get("platform", "unknown"),
            calendar_source=data.get("calendar_source"),
            event_id=data.get("event_id"),
            meeting_link=data.get("meeting_link", ""),
            llm_backend=data.get("llm_backend"),
            audio_warnings=list(data.get("audio_warnings", [])),
            system_audio_devices_seen=list(data.get("system_audio_devices_seen", [])),
            recording_started_at=recording_started_at,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "org": self.org,
            "note_path": self.note_path,
            "title": self.title,
            "date": self.date,
            "participants": [p.to_dict() for p in self.participants],
            "platform": self.platform,
            "calendar_source": self.calendar_source,
            "event_id": self.event_id,
            "meeting_link": self.meeting_link,
            "llm_backend": self.llm_backend,
            "audio_warnings": list(self.audio_warnings),
            "system_audio_devices_seen": list(self.system_audio_devices_seen),
            "recording_started_at": (
                self.recording_started_at.isoformat()
                if self.recording_started_at is not None
                else None
            ),
        }

    def to_meeting_metadata(self) -> MeetingMetadata:
        return MeetingMetadata(
            title=self.title,
            date=date.fromisoformat(self.date),
            participants=list(self.participants),
            platform=self.platform,
        )


def metadata_path(audio_path: pathlib.Path) -> pathlib.Path:
    return audio_path.with_suffix(".metadata.json")


def transcript_path(audio_path: pathlib.Path) -> pathlib.Path:
    return audio_path.with_suffix(".transcript.json")


def analysis_path(audio_path: pathlib.Path) -> pathlib.Path:
    return audio_path.with_suffix(".analysis.json")


def speakers_path(audio_path: pathlib.Path) -> pathlib.Path:
    return audio_path.with_suffix(".speakers.json")


def resolve_recording_path(
    recordings_path: pathlib.Path, stem: str,
) -> pathlib.Path | None:
    """Resolve a bare recording stem to its on-disk file.

    Precedence: .flac first, then .m4a. Returns None if neither exists.
    Used by /api/meetings/speakers (Task 7, 14) and /api/recordings/{stem}/clip
    so both endpoints agree on which artifact is the source of truth.
    """
    flac = recordings_path / f"{stem}.flac"
    if flac.exists():
        return flac
    m4a = recordings_path / f"{stem}.m4a"
    if m4a.exists():
        return m4a
    return None


def write_recording_metadata(audio_path: pathlib.Path, metadata: RecordingMetadata) -> pathlib.Path:
    """Write the sidecar atomically (temp + os.replace).

    Upgraded from direct write in #33 because the retroactive-bind flow
    requires crash-safe sidecar rewrites. Pre-existing callers (recorder
    start, #29 on_before_finalize, pipeline reprocess) get stronger
    crash semantics for free.
    """
    path = metadata_path(audio_path)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    try:
        tmp_path.write_text(
            json.dumps(metadata.to_dict(), indent=2),
            encoding="utf-8",
        )
        os.replace(tmp_path, path)
    except OSError:
        if tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:
                pass
        raise
    return path


def load_recording_metadata(audio_path: pathlib.Path) -> RecordingMetadata | None:
    path = metadata_path(audio_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RecordingMetadata.from_dict(data)


def rebind_recording_metadata_to_event(
    audio_path: pathlib.Path,
    *,
    event_id: str,
    note_path: str,
    calendar_source: str | None,
    meeting_link: str | None,
    title: str | None,
) -> None:
    """Rewrite sidecar from unscheduled state to bound-event state.

    Called by the retroactive-bind flow (#33). Source unscheduled sidecar
    has event_id starting with "unscheduled:"; this helper overwrites it
    with the real event_id + linked calendar metadata so future
    reprocesses treat it as scheduled.

    Optional fields (calendar_source, meeting_link, title) leave the
    existing sidecar value when None. This lets callers skip rewriting
    a field they don't have fresh data for.

    Raises ValueError if the sidecar does not exist.
    """
    rm = load_recording_metadata(audio_path)
    if rm is None:
        raise ValueError(f"no sidecar for {audio_path}")
    rm.event_id = event_id
    rm.note_path = note_path
    if calendar_source is not None:
        rm.calendar_source = calendar_source
    if meeting_link is not None:
        rm.meeting_link = meeting_link
    if title is not None:
        rm.title = title
    write_recording_metadata(audio_path, rm)


def save_transcript(audio_path: pathlib.Path, transcript: TranscriptResult) -> pathlib.Path:
    path = transcript_path(audio_path)
    path.write_text(json.dumps(transcript.to_dict(), indent=2), encoding="utf-8")
    return path


def load_transcript(audio_path: pathlib.Path) -> TranscriptResult | None:
    path = transcript_path(audio_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return TranscriptResult.from_dict(data)


def save_analysis(audio_path: pathlib.Path, analysis: AnalysisResult) -> pathlib.Path:
    path = analysis_path(audio_path)
    path.write_text(json.dumps(analysis.to_dict(), indent=2), encoding="utf-8")
    return path


def load_analysis(audio_path: pathlib.Path) -> AnalysisResult | None:
    path = analysis_path(audio_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return AnalysisResult.from_dict(data)
