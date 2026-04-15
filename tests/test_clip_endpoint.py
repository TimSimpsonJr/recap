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
