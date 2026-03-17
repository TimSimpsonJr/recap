# Core Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python package that takes an audio/video file + meeting metadata JSON and produces Obsidian vault meeting notes, people/company profile stubs, and Todoist tasks.

**Architecture:** Sequential pipeline in a `recap` Python package. WhisperX for transcription+diarization, ffmpeg for frame extraction, Claude Code CLI (`--print`) for AI analysis, Todoist REST API for task creation. Designed as library modules for future Tauri app integration, with a thin CLI test harness.

**Tech Stack:** Python 3.10+, uv, WhisperX, ffmpeg-python, todoist-api-python, PyYAML, pytest

**Design doc:** `docs/plans/2026-03-16-core-pipeline-design.md`

---

### Task 1: Project Scaffolding

**Files:**
- Create: `pyproject.toml`
- Create: `recap/__init__.py`
- Create: `recap/__main__.py`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`
- Create: `config.example.yaml`
- Modify: `.gitignore`

**Step 1: Initialize uv project**

Run:
```bash
uv init --package --python 3.10
```

If uv is not installed:
```bash
pip install uv
```

**Step 2: Configure pyproject.toml**

Replace the generated `pyproject.toml` with:

```toml
[project]
name = "recap"
version = "0.1.0"
description = "Meeting recording → transcription → analysis → Obsidian vault notes + Todoist tasks"
requires-python = ">=3.10"
dependencies = [
    "pyyaml>=6.0",
]

[project.optional-dependencies]
ml = [
    "whisperx>=3.1.0",
]
todoist = [
    "todoist-api-python>=2.1.0",
]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
]

[tool.uv]
# PyTorch CUDA index for GPU packages
extra-index-url = ["https://download.pytorch.org/whl/cu121"]

[tool.pytest.ini_options]
testpaths = ["tests"]
```

Note: `whisperx` and `todoist-api-python` are optional extras so the package can be imported and tested without GPU/network dependencies. Core modules (models, config, vault) only need `pyyaml`.

**Step 3: Create package files**

`recap/__init__.py`:
```python
"""Recap: Meeting recording analysis pipeline."""
```

`recap/__main__.py`:
```python
"""Allow running as python -m recap."""
from recap.cli import main

if __name__ == "__main__":
    main()
```

`tests/__init__.py`: empty file.

`tests/conftest.py`:
```python
"""Shared test fixtures."""
import pathlib
import pytest


@pytest.fixture
def tmp_vault(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary vault structure for testing."""
    meetings = tmp_path / "Work" / "Meetings"
    meetings.mkdir(parents=True)
    people = tmp_path / "Work" / "People"
    people.mkdir(parents=True)
    companies = tmp_path / "Work" / "Companies"
    companies.mkdir(parents=True)
    return tmp_path


@pytest.fixture
def tmp_recordings(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary recordings directory."""
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    return recordings


@pytest.fixture
def tmp_frames(tmp_path: pathlib.Path) -> pathlib.Path:
    """Create a temporary frames directory."""
    frames = tmp_path / "frames"
    frames.mkdir()
    return frames
```

`config.example.yaml`:
```yaml
vault_path: "C:/Users/you/path/to/vault"
recordings_path: "C:/Users/you/recap-data/recordings"
frames_path: "C:/Users/you/recap-data/frames"
user_name: "Your Name"

whisperx:
  model: "large-v3"
  device: "cuda"
  language: "en"

huggingface_token: "hf_your_token_here"

todoist:
  api_token: "your_todoist_api_token"
  default_project: "Recap"
  project_map:
    standup: "Sprint Tasks"
    client-call: "Client Work"
    planning: "Sprint Tasks"
    1:1: "Recap"

claude:
  command: "claude"
```

**Step 4: Update .gitignore**

Append to `.gitignore`:
```
# Config with secrets
config.yaml
!config.example.yaml

# Recap data
recap-data/
```

**Step 5: Install dev dependencies and verify**

Run:
```bash
uv sync --extra dev
```

Then verify:
```bash
uv run pytest --collect-only
```

Expected: pytest finds `tests/` directory, collects 0 tests (none written yet).

**Step 6: Commit**

```bash
git add pyproject.toml recap/__init__.py recap/__main__.py tests/__init__.py tests/conftest.py config.example.yaml .gitignore
git commit -m "feat: scaffold recap Python package with uv"
```

---

### Task 2: Data Models

**Files:**
- Create: `recap/models.py`
- Create: `tests/test_models.py`

**Step 1: Write the failing tests**

`tests/test_models.py`:
```python
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
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_models.py -v`
Expected: ImportError — `recap.models` doesn't exist yet.

**Step 3: Implement models.py**

`recap/models.py`:
```python
"""Data models for the Recap pipeline."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


@dataclass
class Participant:
    name: str
    email: str | None = None


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


@dataclass
class Utterance:
    speaker: str
    start: float
    end: float
    text: str


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


@dataclass
class KeyPoint:
    topic: str
    detail: str

    @classmethod
    def from_dict(cls, data: dict) -> KeyPoint:
        return cls(topic=data["topic"], detail=data["detail"])


@dataclass
class Decision:
    decision: str
    made_by: str

    @classmethod
    def from_dict(cls, data: dict) -> Decision:
        return cls(decision=data["decision"], made_by=data["made_by"])


@dataclass
class FollowUp:
    item: str
    context: str

    @classmethod
    def from_dict(cls, data: dict) -> FollowUp:
        return cls(item=data["item"], context=data["context"])


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


@dataclass
class ProfileStub:
    name: str
    company: str | None = None
    role: str | None = None
    industry: str | None = None


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
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_models.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/models.py tests/test_models.py
git commit -m "feat: add data models for pipeline"
```

---

### Task 3: Config Loading

**Files:**
- Create: `recap/config.py`
- Create: `tests/test_config.py`

**Step 1: Write the failing tests**

`tests/test_config.py`:
```python
"""Tests for config loading."""
import pathlib
import pytest
import yaml

from recap.config import RecapConfig, load_config


class TestRecapConfig:
    def test_load_full_config(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "vault_path": "C:/Users/tim/vault",
            "recordings_path": "C:/Users/tim/recap-data/recordings",
            "frames_path": "C:/Users/tim/recap-data/frames",
            "user_name": "Tim",
            "whisperx": {
                "model": "large-v3",
                "device": "cuda",
                "language": "en",
            },
            "huggingface_token": "hf_test",
            "todoist": {
                "api_token": "test_token",
                "default_project": "Recap",
                "project_map": {"standup": "Sprint Tasks"},
            },
            "claude": {"command": "claude"},
        }))
        config = load_config(config_file)
        assert config.vault_path == pathlib.Path("C:/Users/tim/vault")
        assert config.user_name == "Tim"
        assert config.whisperx.model == "large-v3"
        assert config.todoist.default_project == "Recap"
        assert config.todoist.project_for_type("standup") == "Sprint Tasks"
        assert config.todoist.project_for_type("unknown") == "Recap"

    def test_missing_file_raises(self):
        with pytest.raises(FileNotFoundError):
            load_config(pathlib.Path("/nonexistent/config.yaml"))

    def test_vault_directories(self, tmp_path: pathlib.Path):
        config_file = tmp_path / "config.yaml"
        config_file.write_text(yaml.dump({
            "vault_path": str(tmp_path / "vault"),
            "recordings_path": str(tmp_path / "recordings"),
            "frames_path": str(tmp_path / "frames"),
            "user_name": "Tim",
            "whisperx": {"model": "large-v3", "device": "cuda", "language": "en"},
            "huggingface_token": "hf_test",
            "todoist": {"api_token": "t", "default_project": "Recap", "project_map": {}},
            "claude": {"command": "claude"},
        }))
        config = load_config(config_file)
        assert config.meetings_path == config.vault_path / "Work" / "Meetings"
        assert config.people_path == config.vault_path / "Work" / "People"
        assert config.companies_path == config.vault_path / "Work" / "Companies"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py -v`
Expected: ImportError.

**Step 3: Implement config.py**

`recap/config.py`:
```python
"""Configuration loading for Recap pipeline."""
from __future__ import annotations

import pathlib
from dataclasses import dataclass, field

import yaml


@dataclass
class WhisperXConfig:
    model: str = "large-v3"
    device: str = "cuda"
    language: str = "en"


@dataclass
class TodoistConfig:
    api_token: str = ""
    default_project: str = "Recap"
    project_map: dict[str, str] = field(default_factory=dict)

    def project_for_type(self, meeting_type: str) -> str:
        return self.project_map.get(meeting_type, self.default_project)


@dataclass
class ClaudeConfig:
    command: str = "claude"


@dataclass
class RecapConfig:
    vault_path: pathlib.Path
    recordings_path: pathlib.Path
    frames_path: pathlib.Path
    user_name: str
    whisperx: WhisperXConfig
    huggingface_token: str
    todoist: TodoistConfig
    claude: ClaudeConfig

    @property
    def meetings_path(self) -> pathlib.Path:
        return self.vault_path / "Work" / "Meetings"

    @property
    def people_path(self) -> pathlib.Path:
        return self.vault_path / "Work" / "People"

    @property
    def companies_path(self) -> pathlib.Path:
        return self.vault_path / "Work" / "Companies"

    @property
    def logs_path(self) -> pathlib.Path:
        return self.recordings_path.parent / "logs"

    @property
    def retry_path(self) -> pathlib.Path:
        return self.recordings_path.parent / "todoist-retry.json"


def load_config(path: pathlib.Path) -> RecapConfig:
    if not path.exists():
        raise FileNotFoundError(f"Config file not found: {path}")

    with open(path) as f:
        raw = yaml.safe_load(f)

    wx = raw.get("whisperx", {})
    td = raw.get("todoist", {})
    cl = raw.get("claude", {})

    return RecapConfig(
        vault_path=pathlib.Path(raw["vault_path"]),
        recordings_path=pathlib.Path(raw["recordings_path"]),
        frames_path=pathlib.Path(raw["frames_path"]),
        user_name=raw["user_name"],
        whisperx=WhisperXConfig(
            model=wx.get("model", "large-v3"),
            device=wx.get("device", "cuda"),
            language=wx.get("language", "en"),
        ),
        huggingface_token=raw.get("huggingface_token", ""),
        todoist=TodoistConfig(
            api_token=td.get("api_token", ""),
            default_project=td.get("default_project", "Recap"),
            project_map=td.get("project_map", {}),
        ),
        claude=ClaudeConfig(command=cl.get("command", "claude")),
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/config.py tests/test_config.py
git commit -m "feat: add config loading from YAML"
```

---

### Task 4: Prompt Templates

**Files:**
- Create: `prompts/meeting_analysis.md`

**Step 1: Write the meeting analysis prompt**

`prompts/meeting_analysis.md`:
```markdown
You are a meeting analyst. Analyze the following meeting transcript and metadata, then produce a structured JSON response.

## Participant Roster

The following people were expected in this meeting:

{{participants}}

## Diarized Transcript

The transcript uses speaker labels (SPEAKER_00, SPEAKER_01, etc.) assigned by an automated diarization system. Use conversational context (name mentions, introductions, role references, topics discussed) to map these labels to the participant roster above.

{{transcript}}

## Instructions

Produce a JSON object with exactly these fields:

1. **speaker_mapping** — object mapping each SPEAKER_XX label to a participant name from the roster. If you cannot confidently identify a speaker, use "Unknown Speaker N".

2. **meeting_type** — one of: "standup", "planning", "client-call", "1:1", "interview", "presentation", "workshop", "general". Infer from context.

3. **summary** — 2-3 sentence summary of the meeting's purpose and outcome.

4. **key_points** — array of {topic, detail} objects for the main discussion points.

5. **decisions** — array of {decision, made_by} objects. Null if no decisions were made.

6. **action_items** — array of {assignee, description, due_date, priority} objects. due_date is an ISO date string or null. priority is "high", "normal", or "low".

7. **follow_ups** — array of {item, context} objects for items needing future attention. Null if none.

8. **relationship_notes** — string with context about the working relationship. Only populate for 1:1 meetings, otherwise null.

9. **people** — array of {name, company, role} objects for each person mentioned or participating.

10. **companies** — array of {name, industry} objects for each company mentioned.

Output ONLY valid JSON. No markdown fences, no explanation, no preamble.
```

**Step 2: Commit**

```bash
git add prompts/meeting_analysis.md
git commit -m "feat: add meeting analysis prompt template"
```

---

### Task 5: Transcription Module

**Files:**
- Create: `recap/transcribe.py`
- Create: `tests/test_transcribe.py`

This module wraps WhisperX. Tests mock WhisperX since it requires a GPU.

**Step 1: Write the failing tests**

`tests/test_transcribe.py`:
```python
"""Tests for transcription module."""
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from recap.models import TranscriptResult, Utterance
from recap.transcribe import transcribe, _parse_whisperx_result


class TestParseWhisperxResult:
    """Test parsing of WhisperX output into our models."""

    def test_parse_segments_with_speakers(self):
        whisperx_result = {
            "segments": [
                {
                    "start": 0.0,
                    "end": 3.5,
                    "text": " Hello everyone.",
                    "speaker": "SPEAKER_00",
                },
                {
                    "start": 4.0,
                    "end": 8.2,
                    "text": " Thanks for joining.",
                    "speaker": "SPEAKER_01",
                },
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 2
        assert result.utterances[0].speaker == "SPEAKER_00"
        assert result.utterances[0].text == "Hello everyone."
        assert result.utterances[1].start == 4.0
        assert result.language == "en"

    def test_parse_strips_leading_whitespace(self):
        whisperx_result = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "  Some text  ", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert result.utterances[0].text == "Some text"

    def test_parse_missing_speaker_defaults(self):
        whisperx_result = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello", },
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert result.utterances[0].speaker == "UNKNOWN"

    def test_raw_text_concatenation(self):
        whisperx_result = {
            "segments": [
                {"start": 0.0, "end": 1.0, "text": "Hello.", "speaker": "SPEAKER_00"},
                {"start": 1.5, "end": 3.0, "text": "World.", "speaker": "SPEAKER_01"},
            ],
            "language": "en",
        }
        result = _parse_whisperx_result(whisperx_result)
        assert result.raw_text == "Hello. World."


class TestTranscribe:
    """Test the transcribe function with mocked WhisperX."""

    @patch("recap.transcribe.whisperx")
    def test_transcribe_calls_whisperx(self, mock_wx, tmp_path: pathlib.Path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")

        mock_model = MagicMock()
        mock_wx.load_model.return_value = mock_model
        mock_model.transcribe.return_value = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello.", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }
        mock_diarize_model = MagicMock()
        mock_wx.DiarizationPipeline.return_value = mock_diarize_model
        mock_diarize_model.return_value = "fake_diarize_segments"
        mock_wx.assign_word_speakers.return_value = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello.", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }

        result = transcribe(
            audio_path=audio_file,
            model_name="large-v3",
            device="cpu",
            hf_token="hf_fake",
        )

        assert isinstance(result, TranscriptResult)
        assert len(result.utterances) == 1
        mock_wx.load_model.assert_called_once()

    @patch("recap.transcribe.whisperx")
    def test_transcribe_saves_transcript_json(self, mock_wx, tmp_path: pathlib.Path):
        audio_file = tmp_path / "test.wav"
        audio_file.write_bytes(b"fake audio data")
        transcript_out = tmp_path / "transcript.json"

        mock_model = MagicMock()
        mock_wx.load_model.return_value = mock_model
        mock_model.transcribe.return_value = {
            "segments": [
                {"start": 0.0, "end": 3.0, "text": "Hello.", "speaker": "SPEAKER_00"},
            ],
            "language": "en",
        }
        mock_diarize_model = MagicMock()
        mock_wx.DiarizationPipeline.return_value = mock_diarize_model
        mock_diarize_model.return_value = "fake_segments"
        mock_wx.assign_word_speakers.return_value = mock_model.transcribe.return_value

        result = transcribe(
            audio_path=audio_file,
            model_name="large-v3",
            device="cpu",
            hf_token="hf_fake",
            save_transcript=transcript_out,
        )

        assert transcript_out.exists()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_transcribe.py -v`
Expected: ImportError.

**Step 3: Implement transcribe.py**

`recap/transcribe.py`:
```python
"""Transcription and diarization via WhisperX."""
from __future__ import annotations

import json
import logging
import pathlib

from recap.models import TranscriptResult, Utterance

logger = logging.getLogger(__name__)

try:
    import whisperx
except ImportError:
    whisperx = None  # type: ignore[assignment]


def _parse_whisperx_result(result: dict) -> TranscriptResult:
    utterances = []
    raw_parts = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        speaker = seg.get("speaker", "UNKNOWN")
        utterances.append(
            Utterance(
                speaker=speaker,
                start=seg["start"],
                end=seg["end"],
                text=text,
            )
        )
        raw_parts.append(text)

    return TranscriptResult(
        utterances=utterances,
        raw_text=" ".join(raw_parts),
        language=result.get("language", "unknown"),
    )


def transcribe(
    audio_path: pathlib.Path,
    model_name: str = "large-v3",
    device: str = "cuda",
    hf_token: str = "",
    language: str | None = "en",
    save_transcript: pathlib.Path | None = None,
) -> TranscriptResult:
    if whisperx is None:
        raise ImportError(
            "WhisperX is not installed. Install with: uv sync --extra ml"
        )

    logger.info("Loading WhisperX model %s on %s", model_name, device)
    model = whisperx.load_model(
        model_name, device=device, language=language, compute_type="float16"
    )

    logger.info("Transcribing %s", audio_path)
    audio = whisperx.load_audio(str(audio_path))
    result = model.transcribe(audio, batch_size=16)

    logger.info("Running diarization")
    diarize_model = whisperx.DiarizationPipeline(use_auth_token=hf_token, device=device)
    diarize_segments = diarize_model(audio)
    result = whisperx.assign_word_speakers(diarize_segments, result)

    transcript = _parse_whisperx_result(result)

    if save_transcript:
        logger.info("Saving transcript to %s", save_transcript)
        data = {
            "utterances": [
                {
                    "speaker": u.speaker,
                    "start": u.start,
                    "end": u.end,
                    "text": u.text,
                }
                for u in transcript.utterances
            ],
            "raw_text": transcript.raw_text,
            "language": transcript.language,
        }
        save_transcript.write_text(json.dumps(data, indent=2))

    logger.info(
        "Transcription complete: %d utterances, language=%s",
        len(transcript.utterances),
        transcript.language,
    )
    return transcript
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_transcribe.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/transcribe.py tests/test_transcribe.py
git commit -m "feat: add WhisperX transcription module"
```

---

### Task 6: Frame Extraction Module

**Files:**
- Create: `recap/frames.py`
- Create: `tests/test_frames.py`

This module uses ffmpeg via subprocess for scene-change detection. Tests mock the subprocess call.

**Step 1: Write the failing tests**

`tests/test_frames.py`:
```python
"""Tests for frame extraction module."""
import pathlib
import json
from unittest.mock import patch, MagicMock

import pytest

from recap.frames import extract_frames, _parse_scene_timestamps, FrameResult


class TestParseSceneTimestamps:
    def test_parse_ffprobe_output(self):
        ffprobe_output = "0.000000\n5.234000\n12.567000\n"
        timestamps = _parse_scene_timestamps(ffprobe_output)
        assert timestamps == [0.0, 5.234, 12.567]

    def test_parse_empty_output(self):
        timestamps = _parse_scene_timestamps("")
        assert timestamps == []

    def test_parse_with_trailing_newlines(self):
        timestamps = _parse_scene_timestamps("1.5\n\n\n")
        assert timestamps == [1.5]


class TestExtractFrames:
    @patch("recap.frames.subprocess")
    def test_extract_returns_frame_results(self, mock_sub, tmp_path: pathlib.Path):
        video_file = tmp_path / "meeting.mp4"
        video_file.write_bytes(b"fake video")
        out_dir = tmp_path / "frames"
        out_dir.mkdir()

        # Mock ffprobe for scene detection
        mock_probe = MagicMock()
        mock_probe.stdout = "2.5\n10.0\n"
        mock_probe.returncode = 0

        # Mock ffmpeg for frame extraction
        mock_extract = MagicMock()
        mock_extract.returncode = 0

        mock_sub.run.side_effect = [mock_probe, mock_extract, mock_extract]

        # Create the frames that ffmpeg would create
        (out_dir / "meeting-002.500.png").write_bytes(b"fake png")
        (out_dir / "meeting-010.000.png").write_bytes(b"fake png")

        results = extract_frames(video_file, out_dir)
        assert len(results) == 2
        assert results[0].timestamp == 2.5
        assert results[1].timestamp == 10.0

    @patch("recap.frames.subprocess")
    def test_extract_audio_only_returns_empty(self, mock_sub, tmp_path: pathlib.Path):
        audio_file = tmp_path / "meeting.wav"
        audio_file.write_bytes(b"fake audio")
        out_dir = tmp_path / "frames"
        out_dir.mkdir()

        mock_probe = MagicMock()
        mock_probe.stdout = ""
        mock_probe.returncode = 1

        mock_sub.run.return_value = mock_probe

        results = extract_frames(audio_file, out_dir)
        assert results == []
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_frames.py -v`
Expected: ImportError.

**Step 3: Implement frames.py**

`recap/frames.py`:
```python
"""Frame extraction from video via ffmpeg scene detection."""
from __future__ import annotations

import logging
import pathlib
import subprocess
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass
class FrameResult:
    path: pathlib.Path
    timestamp: float


def _parse_scene_timestamps(ffprobe_output: str) -> list[float]:
    timestamps = []
    for line in ffprobe_output.strip().split("\n"):
        line = line.strip()
        if line:
            try:
                timestamps.append(float(line))
            except ValueError:
                continue
    return timestamps


def extract_frames(
    video_path: pathlib.Path,
    output_dir: pathlib.Path,
    scene_threshold: float = 0.3,
) -> list[FrameResult]:
    stem = video_path.stem

    # Detect scene changes using ffprobe
    logger.info("Detecting scene changes in %s (threshold=%.1f)", video_path, scene_threshold)
    probe_result = subprocess.run(
        [
            "ffprobe",
            "-v", "quiet",
            "-f", "lavfi",
            "-i", f"movie={str(video_path)},select=gt(scene\\,{scene_threshold})",
            "-show_entries", "frame=pts_time",
            "-of", "csv=p=0",
        ],
        capture_output=True,
        text=True,
    )

    if probe_result.returncode != 0:
        logger.warning(
            "Scene detection failed (likely audio-only file): %s",
            probe_result.stderr[:200] if probe_result.stderr else "no stderr",
        )
        return []

    timestamps = _parse_scene_timestamps(probe_result.stdout)
    if not timestamps:
        logger.info("No scene changes detected")
        return []

    logger.info("Found %d scene changes, extracting frames", len(timestamps))

    results = []
    for ts in timestamps:
        filename = f"{stem}-{ts:07.3f}.png"
        out_path = output_dir / filename

        extract_result = subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-ss", str(ts),
                "-i", str(video_path),
                "-frames:v", "1",
                "-q:v", "2",
                str(out_path),
            ],
            capture_output=True,
            text=True,
        )

        if extract_result.returncode == 0 and out_path.exists():
            results.append(FrameResult(path=out_path, timestamp=ts))
        else:
            logger.warning("Failed to extract frame at %.3fs", ts)

    logger.info("Extracted %d frames", len(results))
    return results
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_frames.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/frames.py tests/test_frames.py
git commit -m "feat: add ffmpeg scene-detection frame extraction"
```

---

### Task 7: Claude Analysis Module

**Files:**
- Create: `recap/analyze.py`
- Create: `tests/test_analyze.py`

**Step 1: Write the failing tests**

`tests/test_analyze.py`:
```python
"""Tests for Claude analysis module."""
import json
import pathlib
from unittest.mock import patch, MagicMock

import pytest

from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    Participant,
    TranscriptResult,
    Utterance,
)
from recap.analyze import analyze, _build_prompt, _parse_claude_output


@pytest.fixture
def sample_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hi Jane, thanks for joining."),
            Utterance(speaker="SPEAKER_01", start=3.5, end=7.0, text="Happy to be here, Tim."),
        ],
        raw_text="Hi Jane, thanks for joining. Happy to be here, Tim.",
        language="en",
    )


@pytest.fixture
def sample_metadata() -> MeetingMetadata:
    from datetime import date
    return MeetingMetadata(
        title="Project Kickoff",
        date=date(2026, 3, 16),
        participants=[
            Participant(name="Tim", email="tim@example.com"),
            Participant(name="Jane Smith", email="jane@acme.com"),
        ],
        platform="zoom",
    )


@pytest.fixture
def sample_claude_json() -> dict:
    return {
        "speaker_mapping": {"SPEAKER_00": "Tim", "SPEAKER_01": "Jane Smith"},
        "meeting_type": "client-call",
        "summary": "Project kickoff discussion.",
        "key_points": [{"topic": "Timeline", "detail": "Q3 target"}],
        "decisions": [{"decision": "Use vendor X", "made_by": "Jane Smith"}],
        "action_items": [
            {
                "assignee": "Tim",
                "description": "Send proposal",
                "due_date": "2026-03-20",
                "priority": "high",
            }
        ],
        "follow_ups": None,
        "relationship_notes": None,
        "people": [{"name": "Jane Smith", "company": "Acme Corp", "role": "VP Engineering"}],
        "companies": [{"name": "Acme Corp", "industry": "SaaS"}],
    }


class TestBuildPrompt:
    def test_includes_transcript(self, sample_transcript, sample_metadata):
        prompt_template = "Roster:\n{{participants}}\n\nTranscript:\n{{transcript}}"
        prompt = _build_prompt(prompt_template, sample_transcript, sample_metadata)
        assert "SPEAKER_00: Hi Jane" in prompt
        assert "Tim (tim@example.com)" in prompt

    def test_includes_all_participants(self, sample_transcript, sample_metadata):
        prompt_template = "{{participants}}\n{{transcript}}"
        prompt = _build_prompt(prompt_template, sample_transcript, sample_metadata)
        assert "Tim" in prompt
        assert "Jane Smith" in prompt


class TestParseClaude:
    def test_parse_valid_json(self, sample_claude_json):
        raw = json.dumps(sample_claude_json)
        result = _parse_claude_output(raw)
        assert isinstance(result, AnalysisResult)
        assert result.meeting_type == "client-call"
        assert len(result.action_items) == 1

    def test_parse_json_with_markdown_fences(self, sample_claude_json):
        raw = f"```json\n{json.dumps(sample_claude_json)}\n```"
        result = _parse_claude_output(raw)
        assert result.meeting_type == "client-call"

    def test_parse_invalid_json_raises(self):
        with pytest.raises(ValueError, match="Failed to parse"):
            _parse_claude_output("this is not json at all")


class TestAnalyze:
    @patch("recap.analyze.subprocess")
    def test_analyze_invokes_claude(
        self, mock_sub, sample_transcript, sample_metadata, sample_claude_json, tmp_path
    ):
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("{{participants}}\n{{transcript}}")

        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.stdout = json.dumps(sample_claude_json)
        mock_sub.run.return_value = mock_proc

        result = analyze(
            transcript=sample_transcript,
            metadata=sample_metadata,
            prompt_path=prompt_path,
            claude_command="claude",
        )

        assert isinstance(result, AnalysisResult)
        mock_sub.run.assert_called_once()
        call_args = mock_sub.run.call_args
        assert "--print" in call_args[0][0]

    @patch("recap.analyze.subprocess")
    @patch("recap.analyze.time.sleep")
    def test_analyze_retries_on_failure(
        self, mock_sleep, mock_sub, sample_transcript, sample_metadata, sample_claude_json, tmp_path
    ):
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("{{participants}}\n{{transcript}}")

        fail_proc = MagicMock()
        fail_proc.returncode = 1
        fail_proc.stderr = "API error"

        success_proc = MagicMock()
        success_proc.returncode = 0
        success_proc.stdout = json.dumps(sample_claude_json)

        mock_sub.run.side_effect = [fail_proc, success_proc]

        result = analyze(
            transcript=sample_transcript,
            metadata=sample_metadata,
            prompt_path=prompt_path,
            claude_command="claude",
        )

        assert isinstance(result, AnalysisResult)
        assert mock_sub.run.call_count == 2
        mock_sleep.assert_called_once_with(2)

    @patch("recap.analyze.subprocess")
    @patch("recap.analyze.time.sleep")
    def test_analyze_raises_after_max_retries(
        self, mock_sleep, mock_sub, sample_transcript, sample_metadata, tmp_path
    ):
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("{{participants}}\n{{transcript}}")

        fail_proc = MagicMock()
        fail_proc.returncode = 1
        fail_proc.stderr = "API error"
        mock_sub.run.return_value = fail_proc

        with pytest.raises(RuntimeError, match="Claude analysis failed"):
            analyze(
                transcript=sample_transcript,
                metadata=sample_metadata,
                prompt_path=prompt_path,
                claude_command="claude",
            )

        assert mock_sub.run.call_count == 3
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_analyze.py -v`
Expected: ImportError.

**Step 3: Implement analyze.py**

`recap/analyze.py`:
```python
"""Claude Code CLI analysis of meeting transcripts."""
from __future__ import annotations

import json
import logging
import pathlib
import re
import subprocess
import time

from recap.models import AnalysisResult, MeetingMetadata, TranscriptResult

logger = logging.getLogger(__name__)

RETRY_DELAYS = [2, 8, 30]
MAX_RETRIES = 3


def _build_prompt(
    template: str,
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
) -> str:
    participants_text = "\n".join(
        f"- {p.name} ({p.email})" if p.email else f"- {p.name}"
        for p in metadata.participants
    )
    transcript_text = transcript.to_labelled_text()
    prompt = template.replace("{{participants}}", participants_text)
    prompt = prompt.replace("{{transcript}}", transcript_text)
    return prompt


def _parse_claude_output(raw: str) -> AnalysisResult:
    text = raw.strip()
    # Strip markdown code fences if present
    fence_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    if fence_match:
        text = fence_match.group(1)

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Failed to parse Claude output as JSON: {e}\nRaw: {text[:500]}")

    return AnalysisResult.from_dict(data)


def analyze(
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
    prompt_path: pathlib.Path,
    claude_command: str = "claude",
) -> AnalysisResult:
    template = prompt_path.read_text(encoding="utf-8")
    prompt = _build_prompt(template, transcript, metadata)

    last_error = ""
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            delay = RETRY_DELAYS[attempt - 1]
            logger.warning(
                "Retry %d/%d after %ds: %s", attempt, MAX_RETRIES, delay, last_error
            )
            time.sleep(delay)

        logger.info("Running Claude analysis (attempt %d/%d)", attempt + 1, MAX_RETRIES)
        result = subprocess.run(
            [claude_command, "--print", "--output-format", "json"],
            input=prompt,
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            last_error = result.stderr[:200] if result.stderr else "unknown error"
            logger.warning("Claude returned non-zero exit code: %s", last_error)
            continue

        try:
            analysis = _parse_claude_output(result.stdout)
            logger.info("Analysis complete: type=%s", analysis.meeting_type)
            return analysis
        except ValueError as e:
            last_error = str(e)
            logger.warning("Failed to parse Claude output: %s", last_error)
            continue

    raise RuntimeError(
        f"Claude analysis failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_analyze.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/analyze.py tests/test_analyze.py
git commit -m "feat: add Claude Code CLI analysis module with retry"
```

---

### Task 8: Vault Writing — Meeting Notes

**Files:**
- Create: `recap/vault.py`
- Create: `tests/test_vault.py`

This is the largest module. We'll build it in two tasks: meeting notes first (this task), then profile stubs and previous meeting search (Task 9).

**Step 1: Write the failing tests**

`tests/test_vault.py`:
```python
"""Tests for vault writing module."""
import pathlib
from datetime import date

import pytest
import yaml

from recap.models import (
    ActionItem,
    AnalysisResult,
    Decision,
    FollowUp,
    KeyPoint,
    MeetingMetadata,
    Participant,
    ProfileStub,
)
from recap.vault import (
    write_meeting_note,
    _generate_meeting_markdown,
    _format_duration,
    _slugify,
)
from recap.frames import FrameResult


@pytest.fixture
def sample_metadata() -> MeetingMetadata:
    return MeetingMetadata(
        title="Project Kickoff with Acme Corp",
        date=date(2026, 3, 16),
        participants=[
            Participant(name="Tim", email="tim@example.com"),
            Participant(name="Jane Smith", email="jane@acme.com"),
        ],
        platform="zoom",
    )


@pytest.fixture
def sample_analysis() -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Tim", "SPEAKER_01": "Jane Smith"},
        meeting_type="client-call",
        summary="Discussed project kickoff and timeline.",
        key_points=[
            KeyPoint(topic="Timeline", detail="Q3 delivery target"),
            KeyPoint(topic="Budget", detail="$50k approved"),
        ],
        decisions=[Decision(decision="Use vendor X", made_by="Jane Smith")],
        action_items=[
            ActionItem(assignee="Tim", description="Send proposal by Friday", due_date="2026-03-20", priority="high"),
            ActionItem(assignee="Jane Smith", description="Review budget numbers", due_date=None, priority="normal"),
        ],
        follow_ups=[FollowUp(item="Contract review", context="Legal team pending")],
        relationship_notes=None,
        people=[ProfileStub(name="Jane Smith", company="Acme Corp", role="VP Engineering")],
        companies=[ProfileStub(name="Acme Corp", industry="SaaS")],
    )


class TestSlugify:
    def test_basic(self):
        assert _slugify("Project Kickoff with Acme Corp") == "project-kickoff-with-acme-corp"

    def test_special_chars(self):
        assert _slugify("Q3 Review: Budget & Timeline") == "q3-review-budget-timeline"


class TestFormatDuration:
    def test_minutes_only(self):
        assert _format_duration(2700.0) == "45m"

    def test_hours_and_minutes(self):
        assert _format_duration(5400.0) == "1h 30m"

    def test_round_hour(self):
        assert _format_duration(3600.0) == "1h 0m"


class TestGenerateMeetingMarkdown:
    def test_includes_frontmatter(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/recap-data/recordings/2026-03-16-kickoff.mp4"),
        )
        # Parse frontmatter
        parts = md.split("---\n")
        assert len(parts) >= 3
        fm = yaml.safe_load(parts[1])
        assert fm["date"] == "2026-03-16"
        assert "[[Tim]]" in fm["participants"]
        assert "[[Acme Corp]]" in fm["companies"]
        assert fm["platform"] == "zoom"
        assert fm["type"] == "client-call"
        assert "meeting/client-call" in fm["tags"]

    def test_includes_summary(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Summary" in md
        assert "Discussed project kickoff" in md

    def test_includes_key_points(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Key Points" in md
        assert "Timeline" in md

    def test_includes_decisions_when_present(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Decisions Made" in md
        assert "Use vendor X" in md

    def test_omits_decisions_when_empty(self, sample_metadata, sample_analysis):
        sample_analysis.decisions = []
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Decisions Made" not in md

    def test_includes_action_items(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Action Items" in md
        assert "- [ ] Tim: Send proposal by Friday" in md
        assert "- [ ] [[Jane Smith]]: Review budget numbers" in md

    def test_omits_relationship_notes_when_null(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Relationship Notes" not in md

    def test_includes_relationship_notes_when_present(self, sample_metadata, sample_analysis):
        sample_analysis.relationship_notes = "Jane prefers async communication."
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
        )
        assert "## Relationship Notes" in md
        assert "Jane prefers async" in md

    def test_includes_frames_when_present(self, sample_metadata, sample_analysis):
        frames = [
            FrameResult(path=pathlib.Path("frames/meeting-002.500.png"), timestamp=2.5),
            FrameResult(path=pathlib.Path("frames/meeting-010.000.png"), timestamp=10.0),
        ]
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            frames=frames,
        )
        assert "## Screenshots" in md
        assert "![[meeting-002.500.png]]" in md
        assert "0:02" in md

    def test_user_action_items_tagged_todoist(self, sample_metadata, sample_analysis):
        md = _generate_meeting_markdown(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            user_name="Tim",
        )
        assert "Send proposal by Friday #todoist" in md
        assert "#todoist" not in md.split("Jane Smith")[1].split("\n")[0]


class TestWriteMeetingNote:
    def test_writes_file(self, tmp_vault, sample_metadata, sample_analysis):
        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            meetings_dir=tmp_vault / "Work" / "Meetings",
        )
        assert note_path.exists()
        assert note_path.name == "2026-03-16 - Project Kickoff with Acme Corp.md"

    def test_skips_if_exists(self, tmp_vault, sample_metadata, sample_analysis):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        existing = meetings_dir / "2026-03-16 - Project Kickoff with Acme Corp.md"
        existing.write_text("existing content")

        note_path = write_meeting_note(
            metadata=sample_metadata,
            analysis=sample_analysis,
            duration_seconds=2700.0,
            recording_path=pathlib.Path("C:/rec/test.mp4"),
            meetings_dir=meetings_dir,
        )
        assert note_path is None
        assert existing.read_text() == "existing content"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault.py -v`
Expected: ImportError.

**Step 3: Implement vault.py**

`recap/vault.py`:
```python
"""Obsidian vault writing — meeting notes, profile stubs, previous meeting search."""
from __future__ import annotations

import logging
import pathlib
import re
from datetime import date

import yaml

from recap.frames import FrameResult
from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    ProfileStub,
)

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    slug = text.lower()
    slug = re.sub(r"[^a-z0-9\s-]", "", slug)
    slug = re.sub(r"[\s]+", "-", slug)
    return slug.strip("-")


def _format_duration(seconds: float) -> str:
    total_minutes = int(seconds // 60)
    hours = total_minutes // 60
    minutes = total_minutes % 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _format_timestamp(seconds: float) -> str:
    m = int(seconds // 60)
    s = int(seconds % 60)
    return f"{m}:{s:02d}"


def _generate_meeting_markdown(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    frames: list[FrameResult] | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
) -> str:
    # Frontmatter
    fm = {
        "date": metadata.date.isoformat(),
        "participants": [f"[[{p.name}]]" for p in metadata.participants],
        "companies": [f"[[{c.name}]]" for c in analysis.companies],
        "platform": metadata.platform,
        "duration": _format_duration(duration_seconds),
        "recording": str(recording_path),
        "type": analysis.meeting_type,
        "tags": [f"meeting/{analysis.meeting_type}"],
    }
    lines = ["---"]
    lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")

    # Summary
    lines.append("## Summary")
    lines.append("")
    lines.append(analysis.summary)
    lines.append("")

    # Key Points
    if analysis.key_points:
        lines.append("## Key Points")
        lines.append("")
        for kp in analysis.key_points:
            lines.append(f"### {kp.topic}")
            lines.append("")
            lines.append(kp.detail)
            lines.append("")

    # Decisions (conditional)
    if analysis.decisions:
        lines.append("## Decisions Made")
        lines.append("")
        for d in analysis.decisions:
            lines.append(f"- **{d.decision}** (decided by {d.made_by})")
        lines.append("")

    # Action Items
    if analysis.action_items:
        lines.append("## Action Items")
        lines.append("")
        for item in analysis.action_items:
            # Wikilink assignees other than the user
            is_user = user_name and item.assignee.lower() == user_name.lower()
            assignee = item.assignee if is_user else f"[[{item.assignee}]]"
            todoist_tag = " #todoist" if is_user else ""
            lines.append(f"- [ ] {assignee}: {item.description}{todoist_tag}")
        lines.append("")

    # Follow-ups (conditional)
    if analysis.follow_ups:
        lines.append("## Follow-up Required")
        lines.append("")
        for fu in analysis.follow_ups:
            lines.append(f"- **{fu.item}** — {fu.context}")
        lines.append("")

    # Relationship Notes (conditional)
    if analysis.relationship_notes:
        lines.append("## Relationship Notes")
        lines.append("")
        lines.append(analysis.relationship_notes)
        lines.append("")

    # Previous Meeting (conditional)
    if previous_meeting:
        lines.append("## Previous Meeting")
        lines.append("")
        lines.append(f"[[{previous_meeting}]]")
        lines.append("")

    # Screenshots (conditional)
    if frames:
        lines.append("## Screenshots")
        lines.append("")
        for frame in frames:
            ts = _format_timestamp(frame.timestamp)
            lines.append(f"![[{frame.path.name}]]")
            lines.append(f"*Frame at {ts}*")
            lines.append("")

    return "\n".join(lines)


def write_meeting_note(
    metadata: MeetingMetadata,
    analysis: AnalysisResult,
    duration_seconds: float,
    recording_path: pathlib.Path,
    meetings_dir: pathlib.Path,
    frames: list[FrameResult] | None = None,
    previous_meeting: str | None = None,
    user_name: str | None = None,
) -> pathlib.Path | None:
    filename = f"{metadata.date.isoformat()} - {metadata.title}.md"
    note_path = meetings_dir / filename

    if note_path.exists():
        logger.warning("Meeting note already exists, skipping: %s", note_path)
        return None

    md = _generate_meeting_markdown(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration_seconds,
        recording_path=recording_path,
        frames=frames,
        previous_meeting=previous_meeting,
        user_name=user_name,
    )

    note_path.write_text(md, encoding="utf-8")
    logger.info("Wrote meeting note: %s", note_path)
    return note_path
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault.py
git commit -m "feat: add vault meeting note generation"
```

---

### Task 9: Vault Writing — Profile Stubs & Previous Meeting Search

**Files:**
- Modify: `recap/vault.py`
- Modify: `tests/test_vault.py`

**Step 1: Add failing tests for profile stubs and previous meeting search**

Append to `tests/test_vault.py`:
```python
from recap.vault import write_profile_stubs, find_previous_meeting


class TestWriteProfileStubs:
    def test_creates_person_stub(self, tmp_vault, sample_analysis):
        created = write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        person_file = tmp_vault / "Work" / "People" / "Jane Smith.md"
        assert person_file.exists()
        content = person_file.read_text()
        assert "Acme Corp" in content
        assert "VP Engineering" in content
        assert "Jane Smith" in created

    def test_creates_company_stub(self, tmp_vault, sample_analysis):
        write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        company_file = tmp_vault / "Work" / "Companies" / "Acme Corp.md"
        assert company_file.exists()
        content = company_file.read_text()
        assert "SaaS" in content

    def test_skips_existing_person(self, tmp_vault, sample_analysis):
        person_file = tmp_vault / "Work" / "People" / "Jane Smith.md"
        person_file.write_text("existing content")
        write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        assert person_file.read_text() == "existing content"

    def test_skips_existing_company(self, tmp_vault, sample_analysis):
        company_file = tmp_vault / "Work" / "Companies" / "Acme Corp.md"
        company_file.write_text("existing content")
        write_profile_stubs(
            analysis=sample_analysis,
            people_dir=tmp_vault / "Work" / "People",
            companies_dir=tmp_vault / "Work" / "Companies",
        )
        assert company_file.read_text() == "existing content"


class TestFindPreviousMeeting:
    def test_finds_matching_meeting(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        old_note = meetings_dir / "2026-03-09 - Weekly Standup.md"
        old_note.write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n---\nContent here"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Weekly Standup.md",
        )
        assert result == "2026-03-09 - Weekly Standup"

    def test_returns_none_when_no_match(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        old_note = meetings_dir / "2026-03-09 - Other Meeting.md"
        old_note.write_text(
            "---\nparticipants:\n  - \"[[Bob]]\"\n  - \"[[Alice]]\"\n---\nContent"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Standup.md",
        )
        assert result is None

    def test_returns_most_recent_match(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        (meetings_dir / "2026-03-02 - Sync.md").write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n---\n"
        )
        (meetings_dir / "2026-03-09 - Sync.md").write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n---\n"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Sync.md",
        )
        assert result == "2026-03-09 - Sync"

    def test_partial_overlap_matches(self, tmp_vault):
        meetings_dir = tmp_vault / "Work" / "Meetings"
        (meetings_dir / "2026-03-09 - Team Sync.md").write_text(
            "---\nparticipants:\n  - \"[[Tim]]\"\n  - \"[[Jane Smith]]\"\n  - \"[[Bob]]\"\n---\n"
        )
        result = find_previous_meeting(
            participant_names=["Tim", "Jane Smith", "Alice"],
            meetings_dir=meetings_dir,
            exclude_filename="2026-03-16 - Team Sync.md",
            min_overlap=0.5,
        )
        # 2 of 3 current participants overlap = 0.67 > 0.5 threshold
        assert result == "2026-03-09 - Team Sync"
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_vault.py -v -k "ProfileStubs or PreviousMeeting"`
Expected: ImportError — `write_profile_stubs` and `find_previous_meeting` don't exist.

**Step 3: Add profile stubs and previous meeting search to vault.py**

Append to `recap/vault.py`:
```python
def _generate_person_stub(stub: ProfileStub) -> str:
    fm = {}
    if stub.company:
        fm["company"] = f"[[{stub.company}]]"
    if stub.role:
        fm["role"] = stub.role

    lines = ["---"]
    if fm:
        lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")
    lines.append("## Key Topics")
    lines.append("")
    lines.append("## Meeting History")
    lines.append("")
    lines.append("[Automatic via Obsidian backlinks]")
    lines.append("")
    return "\n".join(lines)


def _generate_company_stub(stub: ProfileStub) -> str:
    fm = {}
    if stub.industry:
        fm["industry"] = stub.industry

    lines = ["---"]
    if fm:
        lines.append(yaml.dump(fm, default_flow_style=False, sort_keys=False).strip())
    lines.append("---")
    lines.append("")
    lines.append("## Ongoing Themes")
    lines.append("")
    lines.append("## Key Contacts")
    lines.append("")
    lines.append("[Automatic via Obsidian backlinks]")
    lines.append("")
    return "\n".join(lines)


def write_profile_stubs(
    analysis: AnalysisResult,
    people_dir: pathlib.Path,
    companies_dir: pathlib.Path,
) -> list[str]:
    created = []

    for person in analysis.people:
        path = people_dir / f"{person.name}.md"
        if path.exists():
            logger.debug("Person profile exists, skipping: %s", person.name)
            continue
        path.write_text(_generate_person_stub(person), encoding="utf-8")
        logger.info("Created person profile: %s", person.name)
        created.append(person.name)

    for company in analysis.companies:
        path = companies_dir / f"{company.name}.md"
        if path.exists():
            logger.debug("Company profile exists, skipping: %s", company.name)
            continue
        path.write_text(_generate_company_stub(company), encoding="utf-8")
        logger.info("Created company profile: %s", company.name)
        created.append(company.name)

    return created


def _parse_participants_from_frontmatter(content: str) -> list[str]:
    parts = content.split("---\n")
    if len(parts) < 3:
        return []
    try:
        fm = yaml.safe_load(parts[1])
    except yaml.YAMLError:
        return []
    if not fm or "participants" not in fm:
        return []
    names = []
    for p in fm["participants"]:
        # Extract name from "[[Name]]" format
        match = re.search(r"\[\[(.+?)]]", str(p))
        if match:
            names.append(match.group(1))
    return names


def find_previous_meeting(
    participant_names: list[str],
    meetings_dir: pathlib.Path,
    exclude_filename: str,
    min_overlap: float = 0.5,
) -> str | None:
    current_set = set(n.lower() for n in participant_names)
    if not current_set:
        return None

    candidates = []
    for note_path in sorted(meetings_dir.glob("*.md"), reverse=True):
        if note_path.name == exclude_filename:
            continue
        content = note_path.read_text(encoding="utf-8")
        note_participants = _parse_participants_from_frontmatter(content)
        note_set = set(n.lower() for n in note_participants)

        if not note_set:
            continue

        overlap = len(current_set & note_set) / len(current_set)
        if overlap >= min_overlap:
            candidates.append(note_path.stem)
            break  # sorted reverse = most recent first

    return candidates[0] if candidates else None
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_vault.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/vault.py tests/test_vault.py
git commit -m "feat: add profile stubs and previous meeting search"
```

---

### Task 10: Todoist Integration

**Files:**
- Create: `recap/todoist.py`
- Create: `tests/test_todoist.py`

**Step 1: Write the failing tests**

`tests/test_todoist.py`:
```python
"""Tests for Todoist integration."""
import json
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from recap.models import ActionItem, AnalysisResult, KeyPoint, ProfileStub
from recap.todoist import (
    create_tasks,
    _filter_user_items,
    _build_obsidian_uri,
    save_retry_file,
    load_retry_file,
)


@pytest.fixture
def action_items() -> list[ActionItem]:
    return [
        ActionItem(assignee="Tim", description="Send proposal", due_date="2026-03-20", priority="high"),
        ActionItem(assignee="Jane Smith", description="Review budget", due_date=None, priority="normal"),
        ActionItem(assignee="Tim", description="Book room", due_date="next Monday", priority="low"),
    ]


class TestFilterUserItems:
    def test_filters_to_user_only(self, action_items):
        filtered = _filter_user_items(action_items, "Tim")
        assert len(filtered) == 2
        assert all(item.assignee == "Tim" for item in filtered)

    def test_case_insensitive(self, action_items):
        filtered = _filter_user_items(action_items, "tim")
        assert len(filtered) == 2


class TestBuildObsidianUri:
    def test_builds_uri(self):
        uri = _build_obsidian_uri(
            vault_name="Tim's Vault",
            note_path="Work/Meetings/2026-03-16 - Kickoff.md",
        )
        assert "obsidian://open" in uri
        assert "Tim's%20Vault" in uri or "Tim%27s%20Vault" in uri
        assert "Kickoff" in uri


class TestCreateTasks:
    @patch("recap.todoist.TodoistAPI")
    def test_creates_tasks_for_user_items(self, mock_api_cls, action_items):
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api
        mock_task = MagicMock()
        mock_task.id = "123"
        mock_api.add_task.return_value = mock_task

        # Mock get_projects for project lookup
        mock_project = MagicMock()
        mock_project.id = "proj_1"
        mock_project.name = "Client Work"
        mock_api.get_projects.return_value = [mock_project]

        task_ids = create_tasks(
            action_items=action_items,
            user_name="Tim",
            api_token="test_token",
            project_name="Client Work",
            vault_name="Tim's Vault",
            note_path="Work/Meetings/2026-03-16 - Kickoff.md",
        )

        assert len(task_ids) == 2
        assert mock_api.add_task.call_count == 2

    @patch("recap.todoist.TodoistAPI")
    def test_skips_when_no_user_items(self, mock_api_cls, action_items):
        mock_api = MagicMock()
        mock_api_cls.return_value = mock_api

        task_ids = create_tasks(
            action_items=action_items,
            user_name="Bob",
            api_token="test_token",
            project_name="Recap",
            vault_name="Vault",
            note_path="note.md",
        )

        assert task_ids == []
        mock_api.add_task.assert_not_called()


class TestRetryFile:
    def test_save_and_load(self, tmp_path):
        retry_path = tmp_path / "retry.json"
        items = [
            {"description": "Send proposal", "project": "Client Work", "note_path": "test.md"},
        ]
        save_retry_file(items, retry_path)
        assert retry_path.exists()

        loaded = load_retry_file(retry_path)
        assert len(loaded) == 1
        assert loaded[0]["description"] == "Send proposal"

    def test_load_missing_file_returns_empty(self, tmp_path):
        loaded = load_retry_file(tmp_path / "nonexistent.json")
        assert loaded == []

    def test_save_appends(self, tmp_path):
        retry_path = tmp_path / "retry.json"
        save_retry_file([{"a": 1}], retry_path)
        save_retry_file([{"b": 2}], retry_path)
        loaded = load_retry_file(retry_path)
        assert len(loaded) == 2
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_todoist.py -v`
Expected: ImportError.

**Step 3: Implement todoist.py**

`recap/todoist.py`:
```python
"""Todoist task creation from meeting action items."""
from __future__ import annotations

import json
import logging
import pathlib
from urllib.parse import quote

from recap.models import ActionItem

logger = logging.getLogger(__name__)

try:
    from todoist_api_python.api import TodoistAPI
except ImportError:
    TodoistAPI = None  # type: ignore[assignment, misc]


def _filter_user_items(items: list[ActionItem], user_name: str) -> list[ActionItem]:
    return [item for item in items if item.assignee.lower() == user_name.lower()]


def _build_obsidian_uri(vault_name: str, note_path: str) -> str:
    encoded_vault = quote(vault_name)
    encoded_path = quote(note_path)
    return f"obsidian://open?vault={encoded_vault}&file={encoded_path}"


def create_tasks(
    action_items: list[ActionItem],
    user_name: str,
    api_token: str,
    project_name: str,
    vault_name: str,
    note_path: str,
) -> list[str]:
    user_items = _filter_user_items(action_items, user_name)
    if not user_items:
        logger.info("No action items assigned to %s", user_name)
        return []

    if TodoistAPI is None:
        raise ImportError(
            "todoist-api-python is not installed. Install with: uv sync --extra todoist"
        )

    api = TodoistAPI(api_token)
    obsidian_link = _build_obsidian_uri(vault_name, note_path)

    # Find project ID
    project_id = None
    try:
        projects = api.get_projects()
        for proj in projects:
            if proj.name == project_name:
                project_id = proj.id
                break
    except Exception as e:
        logger.warning("Failed to fetch projects, using default: %s", e)

    task_ids = []
    for item in user_items:
        try:
            kwargs = {
                "content": item.description,
                "description": f"From meeting: {obsidian_link}",
                "labels": ["recap"],
            }
            if project_id:
                kwargs["project_id"] = project_id
            if item.due_date:
                kwargs["due_string"] = item.due_date
            if item.priority == "high":
                kwargs["priority"] = 4
            elif item.priority == "low":
                kwargs["priority"] = 2
            else:
                kwargs["priority"] = 3

            task = api.add_task(**kwargs)
            task_ids.append(task.id)
            logger.info("Created Todoist task: %s (id=%s)", item.description, task.id)
        except Exception as e:
            logger.error("Failed to create task '%s': %s", item.description, e)

    return task_ids


def save_retry_file(items: list[dict], path: pathlib.Path) -> None:
    existing = load_retry_file(path)
    existing.extend(items)
    path.write_text(json.dumps(existing, indent=2))
    logger.info("Saved %d items to retry file: %s", len(items), path)


def load_retry_file(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_todoist.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/todoist.py tests/test_todoist.py
git commit -m "feat: add Todoist task creation with retry support"
```

---

### Task 11: Pipeline Orchestrator

**Files:**
- Create: `recap/pipeline.py`
- Create: `tests/test_pipeline.py`

**Step 1: Write the failing tests**

`tests/test_pipeline.py`:
```python
"""Tests for pipeline orchestrator."""
import json
import pathlib
from datetime import date
from unittest.mock import MagicMock, patch, call

import pytest

from recap.config import RecapConfig, WhisperXConfig, TodoistConfig, ClaudeConfig
from recap.models import (
    AnalysisResult,
    ActionItem,
    KeyPoint,
    MeetingMetadata,
    Participant,
    ProfileStub,
    TranscriptResult,
    Utterance,
)
from recap.frames import FrameResult
from recap.pipeline import run_pipeline


@pytest.fixture
def config(tmp_path) -> RecapConfig:
    vault = tmp_path / "vault"
    (vault / "Work" / "Meetings").mkdir(parents=True)
    (vault / "Work" / "People").mkdir(parents=True)
    (vault / "Work" / "Companies").mkdir(parents=True)
    recordings = tmp_path / "recordings"
    recordings.mkdir()
    frames = tmp_path / "frames"
    frames.mkdir()
    (tmp_path / "logs").mkdir()

    return RecapConfig(
        vault_path=vault,
        recordings_path=recordings,
        frames_path=frames,
        user_name="Tim",
        whisperx=WhisperXConfig(),
        huggingface_token="hf_fake",
        todoist=TodoistConfig(api_token="test", default_project="Recap", project_map={}),
        claude=ClaudeConfig(command="claude"),
    )


@pytest.fixture
def metadata_file(tmp_path) -> pathlib.Path:
    meta = {
        "title": "Weekly Standup",
        "date": "2026-03-16",
        "participants": [
            {"name": "Tim", "email": "tim@example.com"},
            {"name": "Jane Smith", "email": "jane@acme.com"},
        ],
        "platform": "zoom",
    }
    path = tmp_path / "meeting.json"
    path.write_text(json.dumps(meta))
    return path


@pytest.fixture
def audio_file(tmp_path) -> pathlib.Path:
    path = tmp_path / "meeting.mp4"
    path.write_bytes(b"fake audio content")
    return path


@pytest.fixture
def mock_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker="SPEAKER_00", start=0.0, end=3.0, text="Hello."),
        ],
        raw_text="Hello.",
        language="en",
    )


@pytest.fixture
def mock_analysis() -> AnalysisResult:
    return AnalysisResult(
        speaker_mapping={"SPEAKER_00": "Tim"},
        meeting_type="standup",
        summary="Quick sync.",
        key_points=[KeyPoint(topic="Status", detail="All on track")],
        decisions=[],
        action_items=[
            ActionItem(assignee="Tim", description="Update board", due_date=None, priority="normal"),
        ],
        follow_ups=[],
        relationship_notes=None,
        people=[ProfileStub(name="Jane Smith", company="Acme Corp", role="Engineer")],
        companies=[ProfileStub(name="Acme Corp", industry="SaaS")],
    )


class TestRunPipeline:
    @patch("recap.pipeline.create_tasks")
    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_full_pipeline(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        mock_todoist,
        config,
        metadata_file,
        audio_file,
        mock_transcript,
        mock_analysis,
    ):
        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []
        mock_analyze.return_value = mock_analysis
        mock_todoist.return_value = ["task_1"]

        result = run_pipeline(audio_file, metadata_file, config)

        assert result["meeting_note"].exists()
        assert "2026-03-16 - Weekly Standup.md" in result["meeting_note"].name
        mock_transcribe.assert_called_once()
        mock_analyze.assert_called_once()
        mock_todoist.assert_called_once()

    @patch("recap.pipeline.create_tasks")
    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pipeline_moves_recording(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        mock_todoist,
        config,
        metadata_file,
        audio_file,
        mock_transcript,
        mock_analysis,
    ):
        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []
        mock_analyze.return_value = mock_analysis
        mock_todoist.return_value = []

        run_pipeline(audio_file, metadata_file, config)

        # Original file should be moved
        assert not audio_file.exists()
        # Should be in recordings dir
        moved = list(config.recordings_path.glob("*.mp4"))
        assert len(moved) == 1
        assert "2026-03-16" in moved[0].name

    @patch("recap.pipeline.save_retry_file")
    @patch("recap.pipeline.create_tasks")
    @patch("recap.pipeline.analyze")
    @patch("recap.pipeline.extract_frames")
    @patch("recap.pipeline.transcribe")
    @patch("recap.pipeline._get_audio_duration")
    def test_pipeline_continues_on_todoist_failure(
        self,
        mock_duration,
        mock_transcribe,
        mock_frames,
        mock_analyze,
        mock_todoist,
        mock_save_retry,
        config,
        metadata_file,
        audio_file,
        mock_transcript,
        mock_analysis,
    ):
        mock_duration.return_value = 1800.0
        mock_transcribe.return_value = mock_transcript
        mock_frames.return_value = []
        mock_analyze.return_value = mock_analysis
        mock_todoist.side_effect = Exception("API down")

        result = run_pipeline(audio_file, metadata_file, config)

        # Meeting note should still be written
        assert result["meeting_note"].exists()
        # Retry file should be saved
        mock_save_retry.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: ImportError.

**Step 3: Implement pipeline.py**

`recap/pipeline.py`:
```python
"""Pipeline orchestrator — ties all modules together."""
from __future__ import annotations

import json
import logging
import pathlib
import shutil
import subprocess

from recap.analyze import analyze
from recap.config import RecapConfig
from recap.frames import extract_frames
from recap.models import MeetingMetadata
from recap.todoist import create_tasks, save_retry_file
from recap.transcribe import transcribe
from recap.vault import find_previous_meeting, write_meeting_note, write_profile_stubs, _slugify

logger = logging.getLogger(__name__)


def _get_audio_duration(path: pathlib.Path) -> float:
    """Get audio/video duration in seconds using ffprobe."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v", "quiet",
                "-show_entries", "format=duration",
                "-of", "csv=p=0",
                str(path),
            ],
            capture_output=True,
            text=True,
        )
        return float(result.stdout.strip())
    except (ValueError, OSError):
        logger.warning("Could not determine audio duration, defaulting to 0")
        return 0.0


def run_pipeline(
    audio_path: pathlib.Path,
    metadata_path: pathlib.Path,
    config: RecapConfig,
) -> dict:
    """Run the full processing pipeline.

    Returns a dict with:
        meeting_note: Path to the generated meeting note (or None)
        recording: Path to the moved recording
        transcript: Path to saved transcript JSON
        todoist_tasks: list of created task IDs
        profiles_created: list of created profile names
        frames: list of extracted frame paths
    """
    results: dict = {}

    # Load metadata
    logger.info("Loading metadata from %s", metadata_path)
    raw_meta = json.loads(metadata_path.read_text())
    metadata = MeetingMetadata.from_dict(raw_meta)

    # Get duration before moving
    duration = _get_audio_duration(audio_path)

    # Move recording to recordings directory
    slug = _slugify(metadata.title)
    ext = audio_path.suffix
    recording_name = f"{metadata.date.isoformat()}-{slug}{ext}"
    recording_dest = config.recordings_path / recording_name
    config.recordings_path.mkdir(parents=True, exist_ok=True)
    shutil.move(str(audio_path), str(recording_dest))
    results["recording"] = recording_dest
    logger.info("Moved recording to %s", recording_dest)

    # Transcribe
    transcript_path = recording_dest.with_suffix(".transcript.json")
    logger.info("Starting transcription")
    transcript = transcribe(
        audio_path=recording_dest,
        model_name=config.whisperx.model,
        device=config.whisperx.device,
        hf_token=config.huggingface_token,
        language=config.whisperx.language,
        save_transcript=transcript_path,
    )
    results["transcript"] = transcript_path

    # Extract frames (video only, warn on failure)
    frames = []
    try:
        config.frames_path.mkdir(parents=True, exist_ok=True)
        frames = extract_frames(recording_dest, config.frames_path)
    except Exception as e:
        logger.warning("Frame extraction failed, continuing: %s", e)
    results["frames"] = [f.path for f in frames]

    # Analyze with Claude
    prompt_path = pathlib.Path(__file__).parent.parent / "prompts" / "meeting_analysis.md"
    logger.info("Starting Claude analysis")
    analysis = analyze(
        transcript=transcript,
        metadata=metadata,
        prompt_path=prompt_path,
        claude_command=config.claude.command,
    )

    # Find previous meeting
    note_filename = f"{metadata.date.isoformat()} - {metadata.title}.md"
    previous = find_previous_meeting(
        participant_names=[p.name for p in metadata.participants],
        meetings_dir=config.meetings_path,
        exclude_filename=note_filename,
    )

    # Write meeting note
    config.meetings_path.mkdir(parents=True, exist_ok=True)
    note_path = write_meeting_note(
        metadata=metadata,
        analysis=analysis,
        duration_seconds=duration,
        recording_path=recording_dest,
        meetings_dir=config.meetings_path,
        frames=frames,
        previous_meeting=previous,
        user_name=config.user_name,
    )
    results["meeting_note"] = note_path

    # Write profile stubs (warn on failure)
    try:
        config.people_path.mkdir(parents=True, exist_ok=True)
        config.companies_path.mkdir(parents=True, exist_ok=True)
        created = write_profile_stubs(
            analysis=analysis,
            people_dir=config.people_path,
            companies_dir=config.companies_path,
        )
        results["profiles_created"] = created
    except Exception as e:
        logger.warning("Profile stub creation failed, continuing: %s", e)
        results["profiles_created"] = []

    # Create Todoist tasks (warn on failure, save retry)
    try:
        project_name = config.todoist.project_for_type(analysis.meeting_type)
        vault_name = config.vault_path.name
        note_rel = f"Work/Meetings/{note_filename}" if note_path else ""
        task_ids = create_tasks(
            action_items=analysis.action_items,
            user_name=config.user_name,
            api_token=config.todoist.api_token,
            project_name=project_name,
            vault_name=vault_name,
            note_path=note_rel,
        )
        results["todoist_tasks"] = task_ids
    except Exception as e:
        logger.warning("Todoist task creation failed, saving to retry: %s", e)
        retry_items = [
            {
                "description": item.description,
                "due_date": item.due_date,
                "priority": item.priority,
                "project": config.todoist.project_for_type(analysis.meeting_type),
                "note_path": note_rel if note_path else "",
            }
            for item in analysis.action_items
            if item.assignee.lower() == config.user_name.lower()
        ]
        save_retry_file(retry_items, config.retry_path)
        results["todoist_tasks"] = []

    logger.info("Pipeline complete")
    return results
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_pipeline.py -v`
Expected: All tests PASS.

**Step 5: Commit**

```bash
git add recap/pipeline.py tests/test_pipeline.py
git commit -m "feat: add pipeline orchestrator"
```

---

### Task 12: CLI Test Harness

**Files:**
- Create: `recap/cli.py`
- Create: `tests/test_cli.py`

**Step 1: Write the failing tests**

`tests/test_cli.py`:
```python
"""Tests for CLI test harness."""
import json
import pathlib
from unittest.mock import patch, MagicMock

import pytest

from recap.cli import main, _parse_args


class TestParseArgs:
    def test_process_command(self):
        args = _parse_args(["process", "meeting.mp4", "meeting.json", "--config", "config.yaml"])
        assert args.command == "process"
        assert args.audio == "meeting.mp4"
        assert args.metadata == "meeting.json"
        assert args.config == "config.yaml"

    def test_retry_todoist_command(self):
        args = _parse_args(["retry-todoist", "--config", "config.yaml"])
        assert args.command == "retry-todoist"


class TestMain:
    @patch("recap.cli.run_pipeline")
    @patch("recap.cli.load_config")
    def test_process_calls_pipeline(self, mock_load_config, mock_run, tmp_path):
        config = MagicMock()
        mock_load_config.return_value = config
        mock_run.return_value = {
            "meeting_note": tmp_path / "note.md",
            "todoist_tasks": ["1"],
            "profiles_created": [],
            "frames": [],
        }

        audio = tmp_path / "meeting.mp4"
        audio.write_bytes(b"fake")
        meta = tmp_path / "meeting.json"
        meta.write_text('{"title":"test","date":"2026-03-16","participants":[],"platform":"zoom"}')
        config_file = tmp_path / "config.yaml"
        config_file.write_text("vault_path: test")

        with patch("sys.argv", ["recap", "process", str(audio), str(meta), "--config", str(config_file)]):
            main()

        mock_run.assert_called_once()
```

**Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cli.py -v`
Expected: ImportError.

**Step 3: Implement cli.py**

`recap/cli.py`:
```python
"""CLI test harness for the Recap pipeline."""
from __future__ import annotations

import argparse
import logging
import pathlib
import sys

from recap.config import load_config
from recap.pipeline import run_pipeline

logger = logging.getLogger(__name__)


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="recap",
        description="Recap: Meeting recording analysis pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # process command
    process_parser = subparsers.add_parser("process", help="Process a meeting recording")
    process_parser.add_argument("audio", help="Path to audio/video file")
    process_parser.add_argument("metadata", help="Path to meeting metadata JSON")
    process_parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )

    # retry-todoist command
    retry_parser = subparsers.add_parser("retry-todoist", help="Retry failed Todoist task creation")
    retry_parser.add_argument(
        "--config", default="config.yaml", help="Path to config file (default: config.yaml)"
    )

    return parser.parse_args(argv)


def _setup_logging(config_path: pathlib.Path) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
        ],
    )


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    _setup_logging(pathlib.Path(args.config))
    config = load_config(pathlib.Path(args.config))

    if args.command == "process":
        audio_path = pathlib.Path(args.audio)
        metadata_path = pathlib.Path(args.metadata)

        if not audio_path.exists():
            logger.error("Audio file not found: %s", audio_path)
            sys.exit(1)
        if not metadata_path.exists():
            logger.error("Metadata file not found: %s", metadata_path)
            sys.exit(1)

        results = run_pipeline(audio_path, metadata_path, config)

        if results.get("meeting_note"):
            logger.info("Meeting note: %s", results["meeting_note"])
        if results.get("todoist_tasks"):
            logger.info("Created %d Todoist tasks", len(results["todoist_tasks"]))
        if results.get("profiles_created"):
            logger.info("Created profiles: %s", ", ".join(results["profiles_created"]))

    elif args.command == "retry-todoist":
        from recap.todoist import load_retry_file, create_tasks

        retry_items = load_retry_file(config.retry_path)
        if not retry_items:
            logger.info("No pending Todoist tasks to retry")
            return

        logger.info("Retrying %d Todoist tasks", len(retry_items))
        # Retry logic would go here — for now just log
        for item in retry_items:
            logger.info("Would retry: %s", item.get("description", "unknown"))


if __name__ == "__main__":
    main()
```

**Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_cli.py -v`
Expected: All tests PASS.

**Step 5: Run full test suite**

Run: `uv run pytest -v`
Expected: All tests across all modules PASS.

**Step 6: Commit**

```bash
git add recap/cli.py recap/__main__.py tests/test_cli.py
git commit -m "feat: add CLI test harness"
```

---

### Task 13: Update MANIFEST.md and PLAN.md

**Files:**
- Modify: `MANIFEST.md`
- Modify: `PLAN.md`

**Step 1: Regenerate MANIFEST.md**

Update to reflect the new package structure. Include all new files with one-line descriptions.

**Step 2: Check off Phase 1 research items in PLAN.md**

Mark all research spike items as complete: `- [x]`

**Step 3: Commit**

```bash
git add MANIFEST.md PLAN.md
git commit -m "docs: update manifest and mark Phase 1 complete"
```
