"""Signal backend routing test (Phase 6 Task 3).

Proves that ``RecordingMetadata.llm_backend`` flows through the real
runtime-config builder and ``run_pipeline`` until it reaches
``subprocess.run`` with the right argv. The analyze-layer unit tests in
``tests/test_analyze.py`` already prove that ``_build_command`` and
``analyze`` dispatch correctly when called directly; this test proves
the PIPELINE wiring delivers the right backend selection to that layer
end-to-end.

Routing path under test:
    RecordingMetadata.llm_backend
      -> recap.daemon.runtime_config.build_runtime_config
      -> PipelineRuntimeConfig.llm_backend
      -> recap.pipeline.run_pipeline
      -> recap.analyze.analyze (backend=config.llm_backend)
      -> recap.analyze.subprocess.run (argv head = "ollama" | "claude")

Mocks at the system boundaries: ML stages (transcribe / diarize) are
mocked because no GPU; FLAC -> AAC conversion is mocked so we don't
need a real encoder; ``recap.analyze.subprocess.run`` is mocked so the
test captures argv without needing a real LLM. The vault writer,
artifacts sidecars, and the real ``build_runtime_config``/``analyze``
code paths all execute for real.
"""
from __future__ import annotations

import json
import pathlib
import shutil
import subprocess
from datetime import date
from unittest.mock import MagicMock, patch

import pytest

from recap.artifacts import RecordingMetadata, write_recording_metadata
from recap.daemon.config import (
    DaemonConfig,
    OrgConfig,
    PipelineSettings,
    RecordingConfig,
)
from recap.daemon.runtime_config import build_runtime_config
from recap.models import MeetingMetadata, Participant, TranscriptResult, Utterance
from recap.pipeline import run_pipeline


# Patch targets match the lazy imports inside ``run_pipeline``. These mirror
# the targets used by tests/test_e2e_pipeline.py (Task 2). The CRITICAL
# difference in this test: we do NOT patch ``recap.analyze.analyze`` -- we
# let the real ``analyze`` run and only mock ``subprocess.run`` at the
# system boundary so we can observe the argv it receives.
_PATCH_TRANSCRIBE = "recap.pipeline.transcribe.transcribe"
_PATCH_DIARIZE = "recap.pipeline.diarize.diarize"
_PATCH_ASSIGN = "recap.pipeline.diarize.assign_speakers"
_PATCH_CONVERT = "recap.pipeline.audio_convert.convert_flac_to_aac"
_PATCH_DELETE_SRC = "recap.pipeline.audio_convert.delete_source_if_configured"
# This is the observation point -- import in analyze.py is
# ``import subprocess``, so ``recap.analyze.subprocess`` is the module
# reference and ``.run`` is the attribute to patch.
_PATCH_SUBPROCESS_RUN = "recap.analyze.subprocess.run"


# Minimum analysis payload the real ``_parse_claude_output`` can consume.
# Keys match ``AnalysisResult.from_dict``'s required shape.
_STUB_ANALYSIS_PAYLOAD = {
    "speaker_mapping": {},
    "meeting_type": "other",
    "summary": "Stubbed analysis for routing test.",
    "key_points": [],
    "decisions": [],
    "action_items": [],
    "follow_ups": None,
    "relationship_notes": None,
    "people": [],
    "companies": [],
}


def _make_silent_flac(path: pathlib.Path, seconds: int = 2) -> None:
    """Generate a short silent FLAC via ffmpeg so ffprobe can read duration.

    Matches tests/test_e2e_pipeline.py so the two tests share the same
    real-audio fixture pattern.
    """
    subprocess.run(
        [
            "ffmpeg", "-y",
            "-f", "lavfi",
            "-i", "anullsrc=channel_layout=mono:sample_rate=16000",
            "-t", str(seconds),
            str(path),
        ],
        check=True,
        capture_output=True,
    )


def _stub_subprocess_result() -> MagicMock:
    """A ``subprocess.CompletedProcess`` shape ``analyze`` parses cleanly."""
    result = MagicMock()
    result.returncode = 0
    result.stdout = json.dumps(_STUB_ANALYSIS_PAYLOAD)
    result.stderr = ""
    return result


@pytest.fixture
def vault_path(tmp_path: pathlib.Path) -> pathlib.Path:
    vault = tmp_path / "vault"
    vault.mkdir()
    return vault


@pytest.fixture
def recordings_path(tmp_path: pathlib.Path) -> pathlib.Path:
    rec = tmp_path / "recordings"
    rec.mkdir()
    return rec


def _make_transcript() -> TranscriptResult:
    return TranscriptResult(
        utterances=[
            Utterance(speaker="Alex", start=1.0, end=4.0, text="Hello."),
        ],
        raw_text="Hello.",
        language="en",
    )


def _make_recording_metadata(llm_backend: str | None) -> RecordingMetadata:
    return RecordingMetadata(
        org="alpha",
        note_path="",
        title="Backend routing",
        date="2026-04-15",
        participants=[Participant(name="Alex")],
        platform="signal",
        llm_backend=llm_backend,
    )


def _make_meeting_metadata() -> MeetingMetadata:
    return MeetingMetadata(
        title="Backend routing",
        date=date(2026, 4, 15),
        participants=[Participant(name="Alex")],
        platform="signal",
    )


def _build_daemon_config(
    vault_path: pathlib.Path,
    recordings_path: pathlib.Path,
) -> DaemonConfig:
    """Minimal DaemonConfig so build_runtime_config can read pipeline + recording."""
    return DaemonConfig(
        vault_path=vault_path,
        recordings_path=recordings_path,
        pipeline=PipelineSettings(
            transcription_model="nvidia/parakeet-tdt-0.6b-v2",
            diarization_model="nvidia/diar_streaming_sortformer_4spk-v2.1",
            auto_retry=False,
            max_retries=0,
        ),
        recording=RecordingConfig(
            archive_format="aac",
            delete_source_after_archive=False,
        ),
    )


def _invoke_pipeline_with_backend(
    audio_path: pathlib.Path,
    vault_path: pathlib.Path,
    recordings_path: pathlib.Path,
    metadata_backend: str | None,
    org_backend: str,
) -> MagicMock:
    """Run the pipeline end-to-end with the requested backends and return the
    ``subprocess.run`` mock so callers can assert on argv.

    ``metadata_backend`` goes on ``RecordingMetadata.llm_backend`` (the Signal
    popup's choice). ``org_backend`` goes on ``OrgConfig.llm_backend`` (the
    org default). ``build_runtime_config`` prefers the metadata backend when
    it is non-None, else falls back to the org backend.
    """
    rec_meta = _make_recording_metadata(metadata_backend)
    write_recording_metadata(audio_path, rec_meta)

    transcript = _make_transcript()
    meeting_metadata = _make_meeting_metadata()

    daemon_config = _build_daemon_config(vault_path, recordings_path)
    org_config = OrgConfig(
        name="alpha",
        subfolder="Clients/Alpha",
        llm_backend=org_backend,
        default=True,
    )

    # This is the routing path under test -- the same call the daemon makes.
    pipeline_config = build_runtime_config(daemon_config, org_config, rec_meta)

    with (
        patch(_PATCH_TRANSCRIBE, return_value=transcript),
        patch(_PATCH_DIARIZE, return_value=[
            {"speaker": "Alex", "start": 1.0, "end": 4.0},
        ]),
        patch(_PATCH_ASSIGN, return_value=transcript),
        patch(_PATCH_CONVERT, return_value=audio_path.with_suffix(".m4a")),
        patch(_PATCH_DELETE_SRC),
        patch(
            _PATCH_SUBPROCESS_RUN,
            return_value=_stub_subprocess_result(),
        ) as mock_subprocess_run,
    ):
        run_pipeline(
            audio_path=audio_path,
            metadata=meeting_metadata,
            config=pipeline_config,
            org_slug="alpha",
            org_subfolder="Clients/Alpha",
            vault_path=vault_path,
            user_name="Tim",
            recording_metadata=rec_meta,
        )

    return mock_subprocess_run


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg + ffprobe required for real audio duration probe",
)
def test_ollama_backend_in_metadata_dispatches_ollama_subprocess(
    vault_path: pathlib.Path,
    recordings_path: pathlib.Path,
) -> None:
    """RecordingMetadata.llm_backend='ollama' -> argv[0]=='ollama'.

    The Signal popup's backend choice (``ollama``) must reach
    ``subprocess.run`` even when the org default says ``claude``. This
    asserts both the metadata-over-org precedence in
    ``build_runtime_config`` and the config->analyze->subprocess chain
    inside ``run_pipeline``.
    """
    audio_path = recordings_path / "ollama-test.flac"
    _make_silent_flac(audio_path)

    mock_subprocess_run = _invoke_pipeline_with_backend(
        audio_path=audio_path,
        vault_path=vault_path,
        recordings_path=recordings_path,
        metadata_backend="ollama",
        # Org default opposite to metadata -- if routing were broken and
        # read the org default directly, this test would catch it.
        org_backend="claude",
    )

    assert mock_subprocess_run.called, (
        "subprocess.run was never called -- pipeline did not reach analyze"
    )
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd[0] == "ollama", (
        f"Expected pipeline to dispatch ollama; got cmd={cmd!r}. "
        f"This means RecordingMetadata.llm_backend did not flow through "
        f"PipelineRuntimeConfig to analyze."
    )
    assert "run" in cmd, f"ollama argv should contain 'run'; got cmd={cmd!r}"


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg + ffprobe required for real audio duration probe",
)
def test_claude_backend_in_metadata_dispatches_claude_subprocess(
    vault_path: pathlib.Path,
    recordings_path: pathlib.Path,
) -> None:
    """Symmetric guard: RecordingMetadata.llm_backend='claude' -> argv[0]=='claude'.

    Catches the mirror-image regression (always-ollama routing). Pairs
    with the ollama test so a future refactor can't accidentally pin
    either direction.
    """
    audio_path = recordings_path / "claude-test.flac"
    _make_silent_flac(audio_path)

    mock_subprocess_run = _invoke_pipeline_with_backend(
        audio_path=audio_path,
        vault_path=vault_path,
        recordings_path=recordings_path,
        metadata_backend="claude",
        # Org default opposite -- same guard as the ollama test.
        org_backend="ollama",
    )

    assert mock_subprocess_run.called, (
        "subprocess.run was never called -- pipeline did not reach analyze"
    )
    cmd = mock_subprocess_run.call_args[0][0]
    assert cmd[0] == "claude", (
        f"Expected pipeline to dispatch claude; got cmd={cmd!r}. "
        f"This means RecordingMetadata.llm_backend did not flow through "
        f"PipelineRuntimeConfig to analyze."
    )
    assert "--print" in cmd, (
        f"claude argv should contain '--print'; got cmd={cmd!r}"
    )
