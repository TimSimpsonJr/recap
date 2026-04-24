"""Tests for data models."""
from datetime import date

from recap.models import (
    ActionItem,
    AnalysisResult,
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
            speaker_id="SPEAKER_00",
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
            Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello."),
            Utterance(speaker_id="SPEAKER_01", speaker="SPEAKER_01", start=3.5, end=7.0, text="Hi there."),
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
            Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello."),
            Utterance(speaker_id="SPEAKER_01", speaker="SPEAKER_01", start=3.5, end=7.0, text="Hi there."),
        ]
        result = TranscriptResult(
            utterances=utterances,
            raw_text="Hello. Hi there.",
            language="en",
        )
        text = result.to_labelled_text()
        assert "SPEAKER_00: Hello." in text
        assert "SPEAKER_01: Hi there." in text


class TestUtteranceSchema:
    """Utterance.speaker_id stable identity + backfill migration (#28)."""

    def test_from_dict_backfills_speaker_id_when_missing(self):
        from recap.models import Utterance
        u = Utterance.from_dict({
            "speaker": "SPEAKER_00",
            "start": 0.0, "end": 1.0, "text": "hi",
        })
        assert u.speaker_id == "SPEAKER_00"
        assert u.speaker == "SPEAKER_00"

    def test_from_dict_preserves_explicit_speaker_id(self):
        from recap.models import Utterance
        u = Utterance.from_dict({
            "speaker_id": "SPEAKER_00",
            "speaker": "Alice",
            "start": 0.0, "end": 1.0, "text": "hi",
        })
        assert u.speaker_id == "SPEAKER_00"
        assert u.speaker == "Alice"

    def test_to_dict_roundtrip_contains_both_fields(self):
        from recap.models import Utterance
        u = Utterance(
            speaker_id="SPEAKER_00", speaker="Alice",
            start=0.0, end=1.0, text="hi",
        )
        d = u.to_dict()
        assert d["speaker_id"] == "SPEAKER_00"
        assert d["speaker"] == "Alice"

    def test_transcript_result_from_dict_delegates_to_utterance(self):
        from recap.models import TranscriptResult
        t = TranscriptResult.from_dict({
            "utterances": [
                {"speaker": "SPEAKER_00", "start": 0, "end": 1, "text": "a"},
                {"speaker": "SPEAKER_01", "start": 1, "end": 2, "text": "b"},
            ],
            "raw_text": "a b",
            "language": "en",
        })
        assert t.utterances[0].speaker_id == "SPEAKER_00"
        assert t.utterances[1].speaker_id == "SPEAKER_01"

    def test_legacy_transcript_all_backfill(self):
        """Transcript with no speaker_id fields anywhere -> every utterance
        backfills speaker_id=speaker."""
        from recap.models import TranscriptResult
        t = TranscriptResult.from_dict({
            "utterances": [
                {"speaker": "Alice", "start": 0, "end": 1, "text": "hi"},
                {"speaker": "Bob", "start": 1, "end": 2, "text": "hey"},
            ],
            "raw_text": "hi hey", "language": "en",
        })
        assert [u.speaker_id for u in t.utterances] == ["Alice", "Bob"]
        assert [u.speaker for u in t.utterances] == ["Alice", "Bob"]


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
