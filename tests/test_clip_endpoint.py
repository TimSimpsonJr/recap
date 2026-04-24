"""Tests for GET /api/recordings/<stem>/clip (Phase 4 Task 12)."""
from __future__ import annotations

import asyncio
import json
import pathlib
import shutil
from unittest.mock import patch

import pytest
import pytest_asyncio

from tests.conftest import AUTH_TOKEN


def _write_transcript(audio_path: pathlib.Path) -> pathlib.Path:
    """Drop a minimal two-speaker transcript next to ``audio_path``."""
    data = {
        "utterances": [
            {
                "speaker": "SPEAKER_00",
                "start": 1.5,
                "end": 3.2,
                "text": "Hello.",
            },
            {
                "speaker": "SPEAKER_01",
                "start": 3.5,
                "end": 6.0,
                "text": "Hi there.",
            },
        ],
        "segments": [],
    }
    path = audio_path.with_suffix(".transcript.json")
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


@pytest_asyncio.fixture
async def clip_fixture(daemon_client):
    """Layer a fake ``<stem>.flac`` + transcript on top of ``daemon_client``.

    The fake FLAC is just a placeholder blob; tests either hit the cache
    path (pre-creating the mp3), or patch ``asyncio.to_thread`` so we
    never actually invoke ffmpeg. The separate ``TestClipIntegration``
    class uses a real FLAC under a skipif guard.
    """
    client, daemon = daemon_client
    recordings = daemon.config.recordings_path
    stem = "meeting-2026-04-14"
    audio_path = recordings / f"{stem}.flac"
    audio_path.write_bytes(b"\x00" * 1024)
    _write_transcript(audio_path)
    return client, daemon, stem


@pytest.mark.asyncio
class TestClipValidation:
    async def test_stem_with_traversal_rejected(self, clip_fixture) -> None:
        client, _, _ = clip_fixture
        # ``aiohttp`` normalises a raw ``..`` in the path, so URL-encode it
        # to smuggle the attempt through to the stem regex.
        resp = await client.get(
            "/api/recordings/..%2Fetc%2Fpasswd/clip?speaker=SPEAKER_00",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status in (400, 404)

    async def test_missing_recording_returns_404(self, clip_fixture) -> None:
        client, _, _ = clip_fixture
        resp = await client.get(
            "/api/recordings/does-not-exist/clip?speaker=SPEAKER_00",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_missing_transcript_returns_404(
        self, clip_fixture,
    ) -> None:
        client, daemon, stem = clip_fixture
        (daemon.config.recordings_path / f"{stem}.transcript.json").unlink()
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_speaker_not_in_transcript_returns_404(
        self, clip_fixture,
    ) -> None:
        client, _, stem = clip_fixture
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_99",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_missing_speaker_param_returns_400(
        self, clip_fixture,
    ) -> None:
        client, _, stem = clip_fixture
        resp = await client.get(
            f"/api/recordings/{stem}/clip",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_duration_out_of_range_returns_400(
        self, clip_fixture,
    ) -> None:
        client, _, stem = clip_fixture
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00&duration=99",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_non_integer_duration_returns_400(
        self, clip_fixture,
    ) -> None:
        client, _, stem = clip_fixture
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00&duration=abc",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_requires_bearer(self, clip_fixture) -> None:
        client, _, stem = clip_fixture
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
        )
        assert resp.status == 401


@pytest.mark.asyncio
class TestClipArchivedRecording:
    """Regression for Task 13 review P1: the pipeline writes ``.m4a``
    to note frontmatter when ``archive-format: aac`` (default) and can
    delete the source ``.flac`` after conversion. The endpoint must
    fall back to the archived file so playback survives that default.
    """

    async def test_m4a_only_recording_resolved(
        self, daemon_client,
    ) -> None:
        client, daemon = daemon_client
        stem = "archived-only"
        m4a_path = daemon.config.recordings_path / f"{stem}.m4a"
        m4a_path.write_bytes(b"\x00" * 1024)
        _write_transcript(m4a_path)  # writes <stem>.transcript.json

        cache_dir = daemon.config.recordings_path / f"{stem}.clips"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "SPEAKER_00_5s.mp3"
        cache_file.write_bytes(b"FAKEMP3")

        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/mpeg"
        assert (await resp.read()) == b"FAKEMP3"

    async def test_flac_preferred_when_both_exist(
        self, daemon_client,
    ) -> None:
        client, daemon = daemon_client
        stem = "both-formats"
        flac_path = daemon.config.recordings_path / f"{stem}.flac"
        m4a_path = daemon.config.recordings_path / f"{stem}.m4a"
        flac_path.write_bytes(b"\x00" * 1024)
        m4a_path.write_bytes(b"\x00" * 512)
        _write_transcript(flac_path)  # <stem>.transcript.json beside FLAC

        captured_cmd: list[list[str]] = []

        async def fake_to_thread(fn, *args, **kwargs):
            captured_cmd.append(list(args[0]))
            cache_dir = daemon.config.recordings_path / f"{stem}.clips"
            cache_dir.mkdir(parents=True, exist_ok=True)
            (cache_dir / "SPEAKER_00_5s.mp3").write_bytes(b"OUT")
            return (0, b"")

        with patch(
            "recap.daemon.server.asyncio.to_thread",
            side_effect=fake_to_thread,
        ):
            resp = await client.get(
                f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            )

        assert resp.status == 200
        # ffmpeg invoked with the FLAC path, not the M4A.
        assert captured_cmd, "ffmpeg was not called"
        assert str(flac_path) in captured_cmd[0]
        assert str(m4a_path) not in captured_cmd[0]


@pytest.mark.asyncio
class TestClipCache:
    async def test_cache_hit_serves_without_ffmpeg(
        self, clip_fixture,
    ) -> None:
        client, daemon, stem = clip_fixture
        cache_dir = daemon.config.recordings_path / f"{stem}.clips"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "SPEAKER_00_5s.mp3"
        cache_file.write_bytes(b"FAKEMP3")

        with patch(
            "recap.daemon.server.asyncio.to_thread",
        ) as mock_to_thread:
            resp = await client.get(
                f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            )

        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/mpeg"
        body = await resp.read()
        assert body == b"FAKEMP3"
        mock_to_thread.assert_not_called()

    async def test_cache_miss_invokes_ffmpeg(self, clip_fixture) -> None:
        client, daemon, stem = clip_fixture
        cache_dir = daemon.config.recordings_path / f"{stem}.clips"
        expected_cache = cache_dir / "SPEAKER_00_5s.mp3"

        async def fake_to_thread(fn, *args, **kwargs):
            # Simulate ffmpeg by writing a stub file to the cache path.
            expected_cache.write_bytes(b"MP3-STUB")
            return (0, b"")

        with patch(
            "recap.daemon.server.asyncio.to_thread",
            side_effect=fake_to_thread,
        ) as mock_to_thread:
            resp = await client.get(
                f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            )

        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/mpeg"
        assert (await resp.read()) == b"MP3-STUB"
        mock_to_thread.assert_called_once()
        assert expected_cache.exists()


@pytest.mark.asyncio
class TestClipFfmpegFailure:
    async def test_ffmpeg_nonzero_returns_500_and_journals(
        self, clip_fixture,
    ) -> None:
        client, daemon, stem = clip_fixture

        async def fake_failing_to_thread(fn, *args, **kwargs):
            return (1, b"ffmpeg: some error")

        with patch(
            "recap.daemon.server.asyncio.to_thread",
            side_effect=fake_failing_to_thread,
        ):
            resp = await client.get(
                f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
                headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            )

        assert resp.status == 500
        events = daemon.event_journal.tail(limit=500)
        assert any(e.get("event") == "clip_extraction_failed" for e in events)


@pytest.mark.asyncio
class TestClipEndpointSpeakerId:
    """Clip lookup + cache filename key on speaker_id (#28)."""

    async def test_accepts_speaker_id_query_param(self, daemon_client) -> None:
        """New speaker_id= param matches against utterance.speaker_id."""
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance

        client, daemon = daemon_client
        stem = "sid-accepts"
        audio = daemon.config.recordings_path / f"{stem}.flac"
        audio.write_bytes(b"\x00" * 1024)
        # Seed transcript where speaker_id != speaker (post-correction state).
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(
                    speaker_id="SPEAKER_00", speaker="Alice",
                    start=0, end=2, text="hi",
                ),
            ],
            raw_text="hi", language="en",
        ))
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker_id=SPEAKER_00&duration=1",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        # Expect either 200 (clip generated) or 500 (ffmpeg fails on the
        # stub FLAC). The key assertion is that the 404 "speaker not
        # found in transcript" does NOT fire — the speaker_id lookup
        # resolved an utterance.
        assert resp.status != 404

    async def test_legacy_speaker_param_still_works(self, daemon_client) -> None:
        """Old speaker= param still resolves for backward compat."""
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance

        client, daemon = daemon_client
        stem = "legacy-speaker"
        audio = daemon.config.recordings_path / f"{stem}.flac"
        audio.write_bytes(b"\x00" * 1024)
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(
                    speaker_id="SPEAKER_00", speaker="SPEAKER_00",
                    start=0, end=2, text="hi",
                ),
            ],
            raw_text="hi", language="en",
        ))
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00&duration=1",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status != 404

    async def test_missing_both_params_returns_400(self, daemon_client) -> None:
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance

        client, daemon = daemon_client
        stem = "missing-both"
        audio = daemon.config.recordings_path / f"{stem}.flac"
        audio.write_bytes(b"\x00" * 1024)
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(
                    speaker_id="SPEAKER_00", speaker="Alice",
                    start=0, end=2, text="hi",
                ),
            ],
            raw_text="hi", language="en",
        ))
        resp = await client.get(
            f"/api/recordings/{stem}/clip?duration=1",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 400

    async def test_speaker_id_not_in_transcript_returns_404(
        self, daemon_client,
    ) -> None:
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance

        client, daemon = daemon_client
        stem = "sid-missing"
        audio = daemon.config.recordings_path / f"{stem}.flac"
        audio.write_bytes(b"\x00" * 1024)
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(
                    speaker_id="SPEAKER_00", speaker="Alice",
                    start=0, end=2, text="hi",
                ),
            ],
            raw_text="hi", language="en",
        ))
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker_id=SPEAKER_99&duration=1",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 404

    async def test_cache_filename_uses_speaker_id(self, daemon_client) -> None:
        """Cache filename key is speaker_id, not display label."""
        from recap.artifacts import save_transcript
        from recap.models import TranscriptResult, Utterance

        client, daemon = daemon_client
        stem = "cache-by-sid"
        audio = daemon.config.recordings_path / f"{stem}.flac"
        audio.write_bytes(b"\x00" * 1024)
        save_transcript(audio, TranscriptResult(
            utterances=[
                Utterance(
                    speaker_id="SPEAKER_00", speaker="Alice",
                    start=0, end=2, text="hi",
                ),
            ],
            raw_text="hi", language="en",
        ))
        # Pre-populate a cache file named by speaker_id.
        cache_dir = daemon.config.recordings_path / f"{stem}.clips"
        cache_dir.mkdir(parents=True, exist_ok=True)
        cache_file = cache_dir / "SPEAKER_00_1s.mp3"
        cache_file.write_bytes(b"cached-clip-content")
        # Hit the endpoint with speaker_id; should serve the cached file.
        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker_id=SPEAKER_00&duration=1",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        body = await resp.read()
        assert body == b"cached-clip-content"


@pytest.mark.asyncio
@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg not installed",
)
class TestClipIntegration:
    async def test_real_ffmpeg_produces_mp3(self, daemon_client) -> None:
        import subprocess

        client, daemon = daemon_client
        stem = "integration-clip"
        audio_path = daemon.config.recordings_path / f"{stem}.flac"
        # 10 seconds of silence, 16kHz mono.
        subprocess.run(
            [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", "anullsrc=channel_layout=mono:sample_rate=16000",
                "-t", "10",
                str(audio_path),
            ],
            check=True,
            capture_output=True,
        )
        _write_transcript(audio_path)

        resp = await client.get(
            f"/api/recordings/{stem}/clip?speaker=SPEAKER_00",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        assert resp.headers["Content-Type"] == "audio/mpeg"
        body = await resp.read()
        assert len(body) > 0
