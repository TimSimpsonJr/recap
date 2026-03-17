"""Tests for data models."""
import json
from datetime import date

from recap.models import (
    ActionItem,
    AnalysisResult,
    KeyPoint,
    Decision,
    FollowUp,
    MeetingMetadata,
    Participant,
    ProfileStub,
    TranscriptResult,
    Utterance,
)


class TestParticipant:
    def test_create(self):
        p = Participant(name="Jane Smith", email="jane@acme.com")
        assert p.name == "Jane Smith"
        assert p.email == "jane@acme.com"

    def test_email_optional(self):
        p = Participant(name="Jane Smith")
        assert p.email is None


class TestMeetingMetadata:
    def test_create(self):
        meta = MeetingMetadata(
            title="Project Kickoff",
            date=date(2026, 3, 16),
            participants=[
                Participant(name="Tim", email="tim@example.com"),
                Participant(name="Jane Smith", email="jane@acme.com"),
            ],
            platform="zoom",
        )
        assert meta.title == "Project Kickoff"
        assert len(meta.participants) == 2
        assert meta.platform == "zoom"

    def test_from_json(self):
        raw = {
            "title": "Standup",
            "date": "2026-03-16",
            "participants": [
                {"name": "Tim", "email": "tim@example.com"},
                {"name": "Jane Smith"},
            ],
            "platform": "teams",
        }
        meta = MeetingMetadata.from_dict(raw)
        assert meta.title == "Standup"
        assert meta.date == date(2026, 3, 16)
        assert meta.participants[1].email is None
        assert meta.platform == "teams"


class TestUtterance:
    def test_create(self):
        u = Utterance(
            speaker="SPEAKER_00",
            start=0.0,
            end=5.2,
            text="Hello everyone.",
        )
        assert u.speaker == "SPEAKER_00"
        assert u.end == 5.2


class TestTranscriptResult:
    def test_create(self):
        utterances = [
            Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello."),
            Utterance(speaker="SPEAKER_01", start=3.5, end=7.0, text="Hi there."),
        ]
        result = TranscriptResult(
            utterances=utterances,
            raw_text="Hello. Hi there.",
            language="en",
        )
        assert len(result.utterances) == 2
        assert result.language == "en"

    def test_to_labelled_text(self):
        utterances = [
            Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello."),
            Utterance(speaker="SPEAKER_01", start=3.5, end=7.0, text="Hi there."),
        ]
        result = TranscriptResult(
            utterances=utterances,
            raw_text="Hello. Hi there.",
            language="en",
        )
        text = result.to_labelled_text()
        assert "SPEAKER_00: Hello." in text
        assert "SPEAKER_01: Hi there." in text


class TestAnalysisResult:
    def test_from_claude_json(self):
        claude_output = {
            "speaker_mapping": {"SPEAKER_00": "Tim", "SPEAKER_01": "Jane Smith"},
            "meeting_type": "client-call",
            "summary": "Discussed the project kickoff.",
            "key_points": [{"topic": "Budget", "detail": "Q3 budget approved"}],
            "decisions": [{"decision": "Use vendor X", "made_by": "Jane Smith"}],
            "action_items": [
                {
                    "assignee": "Tim",
                    "description": "Send proposal",
                    "due_date": "2026-03-20",
                    "priority": "high",
                }
            ],
            "follow_ups": [{"item": "Review contract", "context": "Pending legal"}],
            "relationship_notes": None,
            "people": [
                {"name": "Jane Smith", "company": "Acme Corp", "role": "VP Engineering"}
            ],
            "companies": [{"name": "Acme Corp", "industry": "SaaS"}],
        }
        result = AnalysisResult.from_dict(claude_output)
        assert result.meeting_type == "client-call"
        assert result.speaker_mapping["SPEAKER_00"] == "Tim"
        assert len(result.action_items) == 1
        assert result.action_items[0].assignee == "Tim"
        assert result.relationship_notes is None

    def test_nullable_fields_default_empty(self):
        minimal = {
            "speaker_mapping": {},
            "meeting_type": "standup",
            "summary": "Quick sync.",
            "key_points": [],
            "decisions": None,
            "action_items": [],
            "follow_ups": None,
            "relationship_notes": None,
            "people": [],
            "companies": [],
        }
        result = AnalysisResult.from_dict(minimal)
        assert result.decisions == []
        assert result.follow_ups == []
        assert result.relationship_notes is None


class TestActionItem:
    def test_due_date_optional(self):
        item = ActionItem(
            assignee="Tim",
            description="Do the thing",
            due_date=None,
            priority="normal",
        )
        assert item.due_date is None

    def test_from_dict(self):
        raw = {
            "assignee": "Tim",
            "description": "Send email",
            "due_date": "2026-03-20",
            "priority": "high",
        }
        item = ActionItem.from_dict(raw)
        assert item.due_date == "2026-03-20"


class TestProfileStub:
    def test_person_stub(self):
        stub = ProfileStub(
            name="Jane Smith", company="Acme Corp", role="VP Engineering"
        )
        assert stub.name == "Jane Smith"
        assert stub.company == "Acme Corp"

    def test_company_stub(self):
        stub = ProfileStub(name="Acme Corp", industry="SaaS")
        assert stub.industry == "SaaS"
        assert stub.company is None
