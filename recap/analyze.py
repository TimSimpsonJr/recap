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
        return ["ollama", "run", ollama_model]
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
        result = subprocess.run(
            cmd,
            input=prompt,
            capture_output=True,
            text=True,
        )

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
