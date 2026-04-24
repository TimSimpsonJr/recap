"""Tests for Claude analysis module."""
import json
from datetime import date
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


def _stub_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0.0, end=1.0, text="hi")],
        raw_text="hi",
        language="en",
    )


def _load_template() -> str:
    with open("prompts/meeting_analysis.md", encoding="utf-8") as f:
        return f.read()


def test_build_prompt_with_participants_uses_roster_instructions():
    """Non-empty roster -> participants listed + map-to-roster instruction."""
    template = _load_template()
    meta = MeetingMetadata(
        title="t",
        date=date(2026, 4, 22),
        participants=[
            Participant(name="Alice"),
            Participant(name="Bob", email="b@ex.com"),
        ],
        platform="teams",
    )
    prompt = _build_prompt(template, _stub_transcript(), meta)
    assert "- Alice" in prompt
    assert "- Bob (b@ex.com)" in prompt
    assert "map these labels to the participant roster above" in prompt
    # And the empty-roster wording should NOT appear.
    assert "No participant roster is available" not in prompt


def test_build_prompt_with_empty_roster_uses_no_roster_wording():
    """Empty roster -> replacement wording; contradictory roster instruction gone."""
    template = _load_template()
    meta = MeetingMetadata(
        title="t",
        date=date(2026, 4, 22),
        participants=[],
        platform="teams",
    )
    prompt = _build_prompt(template, _stub_transcript(), meta)
    # The empty-roster wording must appear.
    assert "No participant roster is available" in prompt
    # The contradictory roster instruction must NOT appear.
    assert "map these labels to the participant roster above" not in prompt
    # No participant bullets in the roster section (anywhere before the
    # "## Diarized Transcript" header).
    before_transcript = prompt.split("## Diarized Transcript")[0]
    assert "\n- " not in before_transcript


@pytest.fixture
def sample_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker_id="SPEAKER_00", speaker="SPEAKER_00", start=0.0, end=3.0, text="Hi Jane, thanks for joining."),
            Utterance(speaker_id="SPEAKER_01", speaker="SPEAKER_01", start=3.5, end=7.0, text="Happy to be here, Tim."),
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
        prompt_template = "Roster:\n{{roster_section}}\n\n{{transcript_instruction}}\n\nTranscript:\n{{transcript}}"
        prompt = _build_prompt(prompt_template, sample_transcript, sample_metadata)
        assert "SPEAKER_00: Hi Jane" in prompt
        assert "Tim (tim@example.com)" in prompt

    def test_includes_all_participants(self, sample_transcript, sample_metadata):
        prompt_template = "{{roster_section}}\n{{transcript_instruction}}\n{{transcript}}"
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

    def test_parse_unwraps_claude_cli_envelope(self, sample_claude_json):
        """``claude --print --output-format json`` returns a wrapper envelope
        ``{"type":"result","subtype":"success","result":"<analysis>",...}`` --
        the actual analysis JSON lives inside the ``result`` field as a string.
        The parser must unwrap the envelope before calling
        ``AnalysisResult.from_dict`` or it crashes on ``KeyError: 'meeting_type'``
        (the envelope has no such key)."""
        envelope = {
            "type": "result",
            "subtype": "success",
            "cost_usd": 0.0,
            "duration_ms": 1234,
            "num_turns": 1,
            "result": json.dumps(sample_claude_json),
            "session_id": "deadbeef",
        }
        raw = json.dumps(envelope)
        result = _parse_claude_output(raw)
        assert isinstance(result, AnalysisResult)
        assert result.meeting_type == "client-call"

    def test_parse_unwraps_envelope_with_fenced_inner_result(self, sample_claude_json):
        """Some Claude outputs wrap the analysis JSON in markdown code fences
        INSIDE the envelope's ``result`` string. Unwrapping must strip those
        fences too, not just the top-level ones."""
        inner = f"```json\n{json.dumps(sample_claude_json)}\n```"
        envelope = {"type": "result", "subtype": "success", "result": inner}
        raw = json.dumps(envelope)
        result = _parse_claude_output(raw)
        assert result.meeting_type == "client-call"

    def test_parse_tolerates_raw_newlines_inside_string_values(self, sample_claude_json):
        """Small local models (Qwen 2.5 7B via Ollama ``--format json``)
        sometimes emit JSON where long string values are line-wrapped
        with literal newline characters instead of ``\\n`` escapes:

            "summary": "This is a test meeting to evaluate\\nthe workflow."

        (where the ``\\n`` shown above is an actual newline byte in the
        output, not the two-character escape). Python's strict json
        module rejects these as "Invalid control character". The parser
        must pre-process the text to escape raw newlines that appear
        inside string values, while leaving newlines between tokens
        (which json tolerates) alone.
        """
        # Build a payload where a string spans two physical lines.
        payload = dict(sample_claude_json)
        payload["summary"] = "This is a multi-line summary\nthat wraps across two physical lines."
        # Emit as JSON, then introduce the pathological form by
        # replacing the escape with a raw newline inside the string.
        raw = json.dumps(payload).replace(
            "multi-line summary\\nthat",
            "multi-line summary\nthat",
        )
        result = _parse_claude_output(raw)
        # Newline survives the round-trip as an actual newline in the parsed value.
        assert "\n" in result.summary
        assert "multi-line summary" in result.summary

    def test_parse_tolerates_non_newline_control_chars(self, sample_claude_json):
        """Qwen 2.5 via Ollama has been observed emitting control
        characters other than ``\\n`` inside string values (e.g. form
        feed 0x0c). Python's json rejects anything in 0x00-0x1F with
        ``Invalid control character``. The fix uses ``json.loads(text,
        strict=False)`` which covers the entire control-char range, not
        just a hand-rolled short list of newline/tab/CR. Regression
        guard against re-introducing a partial escaper."""
        payload = dict(sample_claude_json)
        payload["summary"] = "Before\x0cAfter"  # 0x0c form feed
        # Write the JSON as if the model emitted the raw form-feed byte
        # inside the string value (replacing the ``\\u000c`` json.dumps
        # would otherwise produce).
        emitted = json.dumps(payload).replace("Before\\u000cAfter", "Before\x0cAfter")
        result = _parse_claude_output(emitted)
        assert "\x0c" in result.summary
        assert result.summary.startswith("Before")
        assert result.summary.endswith("After")

    def test_parse_preserves_direct_analysis_json_for_ollama(self, sample_claude_json):
        """Ollama (``ollama run --format json``) returns analysis JSON
        directly without the Claude CLI envelope. The unwrap logic must
        NOT mistake a bare analysis dict for an envelope just because a
        ``type`` key happens to appear -- unwrap only when BOTH envelope
        markers are present AND ``result`` is a string."""
        # sample_claude_json has no envelope markers; it's the bare analysis.
        raw = json.dumps(sample_claude_json)
        result = _parse_claude_output(raw)
        assert result.meeting_type == "client-call"


class TestAnalyze:
    @patch("recap.analyze.subprocess")
    def test_analyze_invokes_claude(
        self, mock_sub, sample_transcript, sample_metadata, sample_claude_json, tmp_path
    ):
        prompt_path = tmp_path / "prompt.md"
        prompt_path.write_text("{{roster_section}}\n{{transcript_instruction}}\n{{transcript}}")

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
        prompt_path.write_text("{{roster_section}}\n{{transcript_instruction}}\n{{transcript}}")

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
        prompt_path.write_text("{{roster_section}}\n{{transcript_instruction}}\n{{transcript}}")

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
        prompt_path.write_text("{{roster_section}}\n{{transcript_instruction}}\n{{transcript}}")

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
        prompt_path.write_text("{{roster_section}}\n{{transcript_instruction}}\n{{transcript}}")

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
