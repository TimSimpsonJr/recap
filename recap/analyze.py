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

RETRY_DELAYS = [2, 8]
MAX_RETRIES = 3
ANALYSIS_TIMEOUT_SECONDS = 300


_ROSTER_WITH_PARTICIPANTS = """## Participant Roster

The following people were expected in this meeting:

{bullets}"""

_ROSTER_EMPTY = """## Participant Roster

No participant roster is available for this meeting."""

_TRANSCRIPT_INSTRUCTION_WITH_ROSTER = (
    "The transcript uses speaker labels (SPEAKER_00, SPEAKER_01, etc.) assigned "
    "by an automated diarization system. Use conversational context (name "
    "mentions, introductions, role references, topics discussed) to map these "
    "labels to the participant roster above."
)

_TRANSCRIPT_INSTRUCTION_NO_ROSTER = (
    "The transcript uses speaker labels (SPEAKER_00, SPEAKER_01, etc.) assigned "
    "by an automated diarization system. Only assign a real name if it is "
    "explicitly established in the transcript (e.g. a self-introduction, "
    "'Hi, I'm Alice'). Otherwise keep the speaker_mapping value as "
    "'Unknown Speaker N'."
)


def _build_prompt(
    template: str,
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
) -> str:
    if metadata.participants:
        bullets = "\n".join(
            f"- {p.name} ({p.email})" if p.email else f"- {p.name}"
            for p in metadata.participants
        )
        roster_section = _ROSTER_WITH_PARTICIPANTS.format(bullets=bullets)
        transcript_instruction = _TRANSCRIPT_INSTRUCTION_WITH_ROSTER
    else:
        roster_section = _ROSTER_EMPTY
        transcript_instruction = _TRANSCRIPT_INSTRUCTION_NO_ROSTER

    prompt = template.replace("{{roster_section}}", roster_section)
    prompt = prompt.replace("{{transcript_instruction}}", transcript_instruction)
    prompt = prompt.replace("{{transcript}}", transcript.to_labelled_text())
    return prompt


def _strip_markdown_fence(text: str) -> str:
    """Return ``text`` with a surrounding ```json fence removed, if present."""
    match = re.search(r"```(?:json)?\s*\n(.*?)\n```", text, re.DOTALL)
    return match.group(1) if match else text


def _parse_claude_output(raw: str) -> AnalysisResult:
    text = _strip_markdown_fence(raw.strip())

    # strict=False accepts raw control characters (newlines, tabs, form
    # feeds, etc.) inside JSON string values. Small local LLMs like
    # Qwen 2.5 via ``ollama run --format json`` line-wrap long string
    # values with literal control bytes instead of their ``\\n``
    # escapes. The hand-rolled escaper we tried first only covered
    # ``\\n``/``\\r``/``\\t`` and missed other control chars Qwen
    # actually emits (e.g. 0x0c form feed). strict=False covers the
    # entire 0x00-0x1F range, which is what Python's ``json`` docs
    # prescribe for "control characters will be allowed inside strings".
    try:
        data = json.loads(text, strict=False)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse Claude output as JSON: {e}\nRaw: {text[:500]}"
        )

    # ``claude --print --output-format json`` wraps the model response in an
    # envelope: {"type":"result","subtype":"success","result":"<string>",...}
    # where the actual analysis JSON lives inside the ``result`` field. Only
    # unwrap when BOTH the envelope marker and a string ``result`` payload are
    # present so bare analysis JSON (e.g. from ``ollama run --format json``)
    # passes through untouched.
    if (
        isinstance(data, dict)
        and data.get("type") == "result"
        and isinstance(data.get("result"), str)
    ):
        inner = _strip_markdown_fence(data["result"].strip())
        try:
            data = json.loads(inner, strict=False)
        except json.JSONDecodeError as e:
            raise ValueError(
                f"Failed to parse Claude CLI envelope result as JSON: {e}\n"
                f"Inner: {inner[:500]}"
            )

    return AnalysisResult.from_dict(data)


_BACKEND_LABELS = {
    "claude": "Claude",
    "ollama": "Ollama",
}


def _build_command(
    backend: str,
    claude_command: str,
    claude_model: str,
    ollama_model: str,
) -> list[str]:
    """Build the subprocess command for the chosen backend."""
    if backend == "ollama":
        return ["ollama", "run", ollama_model, "--format", "json"]
    return [claude_command, "--print", "--output-format", "json", "--model", claude_model]


def analyze(
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
    prompt_path: pathlib.Path,
    claude_command: str = "claude",
    claude_model: str = "sonnet",
    backend: str = "claude",
    ollama_model: str = "llama3",
) -> AnalysisResult:
    template = prompt_path.read_text(encoding="utf-8")
    prompt = _build_prompt(template, transcript, metadata)

    # Ollama needs an explicit JSON instruction since it may return plain text
    if backend == "ollama":
        prompt = "You must respond with valid JSON only. No other text.\n\n" + prompt

    label = _BACKEND_LABELS.get(backend, backend)
    last_error = ""
    for attempt in range(MAX_RETRIES):
        if attempt > 0:
            delay = RETRY_DELAYS[attempt - 1]
            logger.warning(
                "Retry %d/%d after %ds: %s", attempt, MAX_RETRIES, delay, last_error
            )
            time.sleep(delay)

        logger.info(
            "Running %s analysis (attempt %d/%d)", label, attempt + 1, MAX_RETRIES
        )
        cmd = _build_command(backend, claude_command, claude_model, ollama_model)
        try:
            result = subprocess.run(
                cmd,
                input=prompt,
                capture_output=True,
                text=True,
                # Force UTF-8 for stdin/stdout. Without this, Windows
                # subprocesses default to the ANSI code page (cp1252),
                # which raises UnicodeDecodeError on any non-Latin-1
                # bytes Ollama/Claude emit (e.g. smart quotes, accented
                # names). ``errors="replace"`` keeps a partial parse
                # possible even if a single byte is malformed rather
                # than losing the whole output.
                encoding="utf-8",
                errors="replace",
                timeout=ANALYSIS_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            last_error = f"{label} timed out after {ANALYSIS_TIMEOUT_SECONDS}s"
            logger.warning(last_error)
            continue

        if result.returncode != 0:
            last_error = result.stderr[:200] if result.stderr else "unknown error"
            logger.warning("%s returned non-zero exit code: %s", label, last_error)
            continue

        try:
            analysis = _parse_claude_output(result.stdout)
            logger.info("Analysis complete: type=%s", analysis.meeting_type)
            return analysis
        except ValueError as e:
            last_error = str(e)
            logger.warning("Failed to parse %s output: %s", label, last_error)
            continue

    raise RuntimeError(
        f"{label} analysis failed after {MAX_RETRIES} attempts. Last error: {last_error}"
    )
