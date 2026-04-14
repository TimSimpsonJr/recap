"""Data models for the Recap pipeline."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date


@dataclass
class Participant:
    name: str
    email: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "email": self.email,
        }


@dataclass
class MeetingMetadata:
    title: str
    date: date
    participants: list[Participant]
    platform: str

    @classmethod
    def from_dict(cls, data: dict) -> MeetingMetadata:
        participants = [
            Participant(name=p["name"], email=p.get("email"))
            for p in data["participants"]
        ]
        d = data["date"]
        if isinstance(d, str):
            d = date.fromisoformat(d)
        return cls(
            title=data["title"],
            date=d,
            participants=participants,
            platform=data["platform"],
        )

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "date": self.date.isoformat(),
            "participants": [p.to_dict() for p in self.participants],
            "platform": self.platform,
        }


@dataclass
class Utterance:
    speaker: str
    start: float
    end: float
    text: str

    def to_dict(self) -> dict:
        return {
            "speaker": self.speaker,
            "start": self.start,
            "end": self.end,
            "text": self.text,
        }


@dataclass
class TranscriptResult:
    utterances: list[Utterance]
    raw_text: str
    language: str

    def to_labelled_text(self) -> str:
        lines = []
        for u in self.utterances:
            lines.append(f"{u.speaker}: {u.text}")
        return "\n".join(lines)

    @classmethod
    def from_dict(cls, data: dict) -> TranscriptResult:
        return cls(
            utterances=[Utterance(**u) for u in data.get("utterances", [])],
            raw_text=data.get("raw_text", ""),
            language=data.get("language", "en"),
        )

    def to_dict(self) -> dict:
        return {
            "utterances": [u.to_dict() for u in self.utterances],
            "raw_text": self.raw_text,
            "language": self.language,
        }


@dataclass
class KeyPoint:
    topic: str
    detail: str

    @classmethod
    def from_dict(cls, data: dict) -> KeyPoint:
        return cls(topic=data["topic"], detail=data["detail"])

    def to_dict(self) -> dict:
        return {
            "topic": self.topic,
            "detail": self.detail,
        }


@dataclass
class Decision:
    decision: str
    made_by: str

    @classmethod
    def from_dict(cls, data: dict) -> Decision:
        return cls(decision=data["decision"], made_by=data["made_by"])

    def to_dict(self) -> dict:
        return {
            "decision": self.decision,
            "made_by": self.made_by,
        }


@dataclass
class FollowUp:
    item: str
    context: str

    @classmethod
    def from_dict(cls, data: dict) -> FollowUp:
        return cls(item=data["item"], context=data["context"])

    def to_dict(self) -> dict:
        return {
            "item": self.item,
            "context": self.context,
        }


@dataclass
class ActionItem:
    assignee: str
    description: str
    due_date: str | None
    priority: str

    @classmethod
    def from_dict(cls, data: dict) -> ActionItem:
        return cls(
            assignee=data["assignee"],
            description=data["description"],
            due_date=data.get("due_date"),
            priority=data.get("priority", "normal"),
        )

    def to_dict(self) -> dict:
        return {
            "assignee": self.assignee,
            "description": self.description,
            "due_date": self.due_date,
            "priority": self.priority,
        }


@dataclass
class ProfileStub:
    name: str
    company: str | None = None
    role: str | None = None
    industry: str | None = None

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "company": self.company,
            "role": self.role,
            "industry": self.industry,
        }


@dataclass
class AnalysisResult:
    speaker_mapping: dict[str, str]
    meeting_type: str
    summary: str
    key_points: list[KeyPoint]
    decisions: list[Decision]
    action_items: list[ActionItem]
    follow_ups: list[FollowUp]
    relationship_notes: str | None
    people: list[ProfileStub]
    companies: list[ProfileStub]

    @classmethod
    def from_dict(cls, data: dict) -> AnalysisResult:
        return cls(
            speaker_mapping=data.get("speaker_mapping", {}),
            meeting_type=data["meeting_type"],
            summary=data["summary"],
            key_points=[
                KeyPoint.from_dict(kp) for kp in (data.get("key_points") or [])
            ],
            decisions=[
                Decision.from_dict(d) for d in (data.get("decisions") or [])
            ],
            action_items=[
                ActionItem.from_dict(a) for a in (data.get("action_items") or [])
            ],
            follow_ups=[
                FollowUp.from_dict(f) for f in (data.get("follow_ups") or [])
            ],
            relationship_notes=data.get("relationship_notes"),
            people=[
                ProfileStub(
                    name=p["name"],
                    company=p.get("company"),
                    role=p.get("role"),
                )
                for p in (data.get("people") or [])
            ],
            companies=[
                ProfileStub(
                    name=c["name"],
                    industry=c.get("industry"),
                )
                for c in (data.get("companies") or [])
            ],
        )

    def to_dict(self) -> dict:
        return {
            "speaker_mapping": dict(self.speaker_mapping),
            "meeting_type": self.meeting_type,
            "summary": self.summary,
            "key_points": [kp.to_dict() for kp in self.key_points],
            "decisions": [d.to_dict() for d in self.decisions],
            "action_items": [a.to_dict() for a in self.action_items],
            "follow_ups": [f.to_dict() for f in self.follow_ups],
            "relationship_notes": self.relationship_notes,
            "people": [p.to_dict() for p in self.people],
            "companies": [c.to_dict() for c in self.companies],
        }
