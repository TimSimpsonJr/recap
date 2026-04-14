"""Helpers for recording sidecar artifacts."""
from __future__ import annotations

import json
import pathlib
import re
from dataclasses import dataclass
from datetime import date
from typing import Any

from recap.models import AnalysisResult, MeetingMetadata, Participant, TranscriptResult


_INVALID_FILENAME_CHARS = re.compile(r'[<>:"/\\|?*]+')


def safe_note_title(title: str) -> str:
    sanitized = _INVALID_FILENAME_CHARS.sub(" ", title).strip()
    sanitized = re.sub(r"\s+", " ", sanitized)
    return sanitized or "Meeting"


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

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> RecordingMetadata:
        participants = [
            Participant(name=p["name"], email=p.get("email"))
            for p in data.get("participants", [])
        ]
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


def write_recording_metadata(audio_path: pathlib.Path, metadata: RecordingMetadata) -> pathlib.Path:
    path = metadata_path(audio_path)
    path.write_text(json.dumps(metadata.to_dict(), indent=2), encoding="utf-8")
    return path


def load_recording_metadata(audio_path: pathlib.Path) -> RecordingMetadata | None:
    path = metadata_path(audio_path)
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return RecordingMetadata.from_dict(data)


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
