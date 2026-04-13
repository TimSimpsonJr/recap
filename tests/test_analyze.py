"""Tests for Claude analysis module."""
import json
from unittest.mock import patch, MagicMock

import pytest

from recap.models import (
    AnalysisResult,
    MeetingMetadata,
    Participant,
    TranscriptResult,
    Utterance,
)
from recap.analyze import analyze, _build_prompt, _build_command, _parse_claude_output


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
        assert result.meeting_type == "client-call"
        assert len(result.action_items) == 1
        assert result.action_items[0].assignee == "Tim"
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
        assert result.meeting_type == "client-call"
        assert len(result.action_items) == 1
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


class TestBuildCommand:
    def test_claude_backend(self):
        cmd = _build_command("claude", "claude", "sonnet", "llama3")
        assert cmd[0] == "claude"
        assert "--print" in cmd

    def test_ollama_backend(self):
        cmd = _build_command("ollama", "claude", "sonnet", "llama3")
        assert cmd[0] == "ollama"
        assert "run" in cmd
        assert "llama3" in cmd
        assert "--format" in cmd
        assert "json" in cmd

    def test_ollama_custom_model(self):
        cmd = _build_command("ollama", "claude", "sonnet", "mistral")
        assert "mistral" in cmd
        assert "--format" in cmd


class TestAnalyzeOllamaBackend:
    @patch("recap.analyze.subprocess")
    def test_uses_ollama_backend(
        self, mock_sub, sample_transcript, sample_metadata, sample_claude_json, tmp_path
    ):
        """When backend='ollama', should call ollama instead of claude."""
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
            backend="ollama",
            ollama_model="llama3",
        )

        assert isinstance(result, AnalysisResult)
        cmd = mock_sub.run.call_args[0][0]
        assert "ollama" in cmd[0]
        assert "llama3" in cmd
        assert "--format" in cmd
        # Verify JSON instruction was prepended to prompt
        input_text = mock_sub.run.call_args[1].get("input") or mock_sub.run.call_args.kwargs.get("input", "")
        assert "You must respond with valid JSON only" in input_text

    @patch("recap.analyze.subprocess")
    def test_ollama_uses_custom_model(
        self, mock_sub, sample_transcript, sample_metadata, sample_claude_json, tmp_path
    ):
        """Ollama backend should use the specified model name."""
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
            backend="ollama",
            ollama_model="mistral",
        )

        assert result.meeting_type == "client-call"
        assert len(result.action_items) == 1
        cmd = mock_sub.run.call_args[0][0]
        assert "mistral" in cmd
