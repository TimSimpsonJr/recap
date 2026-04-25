"""End-to-end #33 retroactive-calendar-bind scenarios.

Combines: plugin POST (simulated via authed aiohttp client) -> daemon HTTP
endpoint -> attach orchestrator -> real disk + EventIndex side effects.
Mirrors ``tests/test_speaker_correction_integration.py``: real ``Daemon``,
real aiohttp client, real disk, no mocks of the orchestrator.

The retroactive-bind flow doesn't invoke the pipeline trigger (no
reprocess), so unlike the #28 harness no trigger stub is wired -- the
endpoint completes synchronously with all side effects on disk.
"""
from __future__ import annotations

import pathlib
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio
import yaml

from recap.daemon.server import create_app
from recap.daemon.service import Daemon
from tests.conftest import AUTH_TOKEN, make_daemon_config


# ---------------------------------------------------------------------------
# Fixture: real Daemon + authed client.
#
# Self-contained so this module mirrors the #28 integration suite shape and
# does not depend on test_daemon_server.py's local ``daemon_client`` fixture
# (which is a separate fixture from the conftest one and overrides it for
# that module). Uses the same org slug ``"d"`` / subfolder ``"Clients/D"``
# as ``make_daemon_config`` so the duplicated seed helpers below stay in
# lockstep with ``tests/test_daemon_server.py::_seed_*_for_attach``.
# ---------------------------------------------------------------------------


_CONFIG_YAML_TEMPLATE = """\
config-version: 1
vault-path: "{vault}"
recordings-path: "{rec}"
user-name: "TestUser"
orgs:
  d:
    subfolder: Clients/D
    llm-backend: claude
    default: true
detection:
  teams:
    enabled: true
    behavior: auto-record
calendars: {{}}
known-contacts: []
recording:
  silence-timeout-minutes: 5
  max-duration-hours: 3
logging:
  retention-days: 7
daemon:
  plugin-port: 9847
"""


@pytest_asyncio.fixture
async def attach_client(aiohttp_client, tmp_path):
    """Return ``(client, daemon)`` with an app wired to a real Daemon.

    Writes a kebab-case config.yaml so ``/api/config`` etc. would also work
    if a test needed them, though the attach-event endpoint does not. The
    ``Daemon`` constructor initializes ``event_index`` from
    ``vault/.recap/event-index.json`` automatically.
    """
    cfg = make_daemon_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        _CONFIG_YAML_TEMPLATE.format(
            vault=(tmp_path / "vault").as_posix(),
            rec=(tmp_path / "rec").as_posix(),
        ),
        encoding="utf-8",
    )
    daemon = Daemon(cfg, config_path=config_path)
    daemon.started_at = (
        datetime.now(timezone.utc).astimezone() - timedelta(seconds=5)
    )
    app = create_app(auth_token=AUTH_TOKEN)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon


# ---------------------------------------------------------------------------
# Seed helpers (duplicated from tests/test_daemon_server.py to keep this
# module self-contained, following the #28 integration suite's convention).
# ---------------------------------------------------------------------------


def _seed_unscheduled(
    daemon, *, stem: str, event_id: str, note_path: str, body: str = "# Source body",
):
    """Seed an audio + sidecar + unscheduled note under ``Clients/D``."""
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.models import Participant

    audio = daemon.config.recordings_path / f"{stem}.flac"
    audio.touch()
    md = RecordingMetadata(
        org="d", note_path=note_path, title="Teams call",
        date="2026-04-24", participants=[Participant(name="Alice")],
        platform="manual",
    )
    md.event_id = event_id
    write_recording_metadata(audio, md)

    vault = daemon.config.vault_path
    (vault / note_path).parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "date": "2026-04-24",
        "time": "14:30-15:15",
        "title": "Teams call",
        "event-id": event_id,
        "org": "d",
        "org-subfolder": "Clients/D",
        "participants": ["[[Alice]]"],
        "companies": [],
        "duration": "45:00",
        "recording": f"{stem}.flac",
        "tags": ["meeting/d", "unscheduled"],
        "pipeline-status": "complete",
    }
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + body
    (vault / note_path).write_text(content, encoding="utf-8")
    daemon.event_index.add(event_id, pathlib.Path(note_path), "d")
    return audio


def _seed_calendar_stub(
    daemon, *, event_id: str, title: str, stub_body: str = "## Agenda\n\n",
    extra_fm: dict | None = None,
):
    """Seed a calendar stub note under ``Clients/D/Meetings``."""
    vault = daemon.config.vault_path
    stub_rel = pathlib.Path(
        "Clients/D/Meetings",
    ) / f"2026-04-24 - {title.lower().replace(' ', '-')}.md"
    full = vault / stub_rel
    full.parent.mkdir(parents=True, exist_ok=True)
    fm = {
        "date": "2026-04-24",
        "time": "14:00-15:00",
        "title": title,
        "event-id": event_id,
        "calendar-source": "google",
        "meeting-link": "https://meet.google.com/xyz",
        "org": "d",
        "org-subfolder": "Clients/D",
        "participants": [],
        "pipeline-status": "pending",
    }
    if extra_fm:
        fm.update(extra_fm)
    content = "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n" + stub_body
    full.write_text(content, encoding="utf-8")
    daemon.event_index.add(event_id, stub_rel, "d")
    return full


# ---------------------------------------------------------------------------
# Scenario 1: happy path -- bind unscheduled to calendar event.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_happy_path_bind_unscheduled_to_calendar_event(attach_client):
    """End-to-end happy path: POST /api/recordings/<stem>/attach-event with
    a synthetic unscheduled recording and an empty-template calendar stub.

    Asserts:
      - 200 status, ``status="ok"``, ``noop=False``
      - merged note exists at the stub's vault-relative path
      - merged frontmatter carries the real event_id
      - merged body contains the source's pipeline output
      - merged note has NO ``## Pre-Meeting Notes`` section (empty stub)
      - sidecar's event_id rewritten to the real event id
      - EventIndex contains only the real entry (synthetic removed)
      - unscheduled note file is gone
    """
    client, daemon = attach_client
    stem = "2026-04-24-1430-teams-call"
    unscheduled_rel = "Clients/D/Meetings/2026-04-24 1430 - Teams call.md"
    audio = _seed_unscheduled(
        daemon, stem=stem, event_id="unscheduled:abc",
        note_path=unscheduled_rel,
        body="# Meeting Summary\n\nPipeline output.",
    )
    stub = _seed_calendar_stub(
        daemon, event_id="E1", title="Sprint Planning",
        stub_body="## Agenda\n\n",
    )

    resp = await client.post(
        f"/api/recordings/{stem}/attach-event",
        json={"event_id": "E1"},
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert body["noop"] is False
    assert body["note_path"].endswith(".md")
    # Vault-relative posix form (no backslashes).
    assert "\\" not in body["note_path"]

    # Merged note on disk at the stub path.
    merged = stub.read_text(encoding="utf-8")
    assert "Pipeline output" in merged
    assert "event-id: E1" in merged
    # Empty-stub heuristic: no Pre-Meeting Notes appendix.
    assert "## Pre-Meeting Notes" not in merged

    # Unscheduled note file removed.
    unscheduled_abs = daemon.config.vault_path / unscheduled_rel
    assert not unscheduled_abs.exists()

    # EventIndex: only real entry, synthetic gone.
    assert daemon.event_index.lookup("unscheduled:abc") is None
    assert daemon.event_index.lookup("E1") is not None

    # Sidecar rewritten with real event_id.
    from recap.artifacts import load_recording_metadata
    loaded = load_recording_metadata(audio)
    assert loaded is not None
    assert loaded.event_id == "E1"


# ---------------------------------------------------------------------------
# Scenario 2: stub had user edits -> Pre-Meeting Notes section preserved.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_bind_preserves_user_edits_under_pre_meeting_notes(attach_client):
    """When the calendar stub body has user edits beyond the empty Agenda
    template, those edits land under a ``## Pre-Meeting Notes`` section in
    the merged note, AFTER the pipeline output.
    """
    client, daemon = attach_client
    stem = "2026-04-24-1430-teams-call"
    _seed_unscheduled(
        daemon, stem=stem, event_id="unscheduled:abc",
        note_path="Clients/D/Meetings/2026-04-24 1430 - Teams call.md",
        body="# Meeting Summary\n\nPipeline output.",
    )
    stub_body = "## Agenda\n\n- Topic 1\n- Topic 2\n\nNotes from prep."
    stub = _seed_calendar_stub(
        daemon, event_id="E1", title="Sprint Planning", stub_body=stub_body,
    )

    resp = await client.post(
        f"/api/recordings/{stem}/attach-event",
        json={"event_id": "E1"},
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "ok"
    assert body["noop"] is False

    merged = stub.read_text(encoding="utf-8")
    # Pre-Meeting Notes section appended.
    assert "## Pre-Meeting Notes" in merged
    # User-edited content preserved.
    assert "Topic 1" in merged
    assert "Topic 2" in merged
    assert "Notes from prep." in merged
    # Pipeline output comes BEFORE Pre-Meeting Notes.
    assert merged.index("Pipeline output") < merged.index("## Pre-Meeting Notes")
    assert merged.index("Meeting Summary") < merged.index("## Pre-Meeting Notes")


# ---------------------------------------------------------------------------
# Scenario 3: replace=True overrides existing recording on the stub.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_replace_path_overrides_existing_recording(attach_client):
    """``replace=True`` permits the bind even when the target stub already
    references a different recording filename.

    Asserts the new recording's pipeline body lands on the stub, the old
    recording's audio + sidecar files remain on disk (per #33's "leave
    orphan artifacts for #39 to handle"), and the stub's ``recording``
    frontmatter field reflects the new filename.
    """
    client, daemon = attach_client
    # Prior recording (untouched-by-bind artifacts to assert remain on disk).
    old_audio = daemon.config.recordings_path / "rec-old.flac"
    old_audio.write_bytes(b"\x00\x00")  # non-empty to confirm we don't truncate
    from recap.artifacts import RecordingMetadata, write_recording_metadata
    from recap.models import Participant
    old_md = RecordingMetadata(
        org="d", note_path="Clients/D/Meetings/old.md", title="Old call",
        date="2026-04-24", participants=[Participant(name="Old")],
        platform="manual",
    )
    old_md.event_id = "E1"
    write_recording_metadata(old_audio, old_md)
    old_sidecar = daemon.config.recordings_path / "rec-old.metadata.json"
    assert old_sidecar.exists(), "sidecar from write_recording_metadata"

    # New unscheduled recording bound to a synthetic event.
    new_audio = _seed_unscheduled(
        daemon, stem="rec-new", event_id="unscheduled:abc",
        note_path="Clients/D/Meetings/u.md",
        body="# Meeting Summary\n\nNew pipeline output.",
    )

    # Calendar stub already carries `recording: rec-old.flac` (mid-state).
    # Body is the empty Agenda template so the merge heuristic produces a
    # clean replacement without an unexpected-shape Pre-Meeting Notes
    # appendix; the focus here is the replace semantics, not the merge
    # heuristic (covered exhaustively in tests/test_attach.py).
    vault = daemon.config.vault_path
    stub_rel = pathlib.Path("Clients/D/Meetings/2026-04-24 - sprint.md")
    fm = {
        "date": "2026-04-24",
        "time": "14:00-15:00",
        "title": "Sprint",
        "event-id": "E1",
        "calendar-source": "google",
        "meeting-link": "https://meet.google.com/x",
        "org": "d",
        "org-subfolder": "Clients/D",
        "recording": "rec-old.flac",
        "pipeline-status": "complete",
    }
    (vault / stub_rel).write_text(
        "---\n" + yaml.dump(fm, sort_keys=False) + "---\n\n## Agenda\n\n",
        encoding="utf-8",
    )
    daemon.event_index.add("E1", stub_rel, "d")

    resp = await client.post(
        "/api/recordings/rec-new/attach-event",
        json={"event_id": "E1", "replace": True},
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert data["noop"] is False

    # Stub now references rec-new.flac and contains the new pipeline body.
    merged = (vault / stub_rel).read_text(encoding="utf-8")
    assert "rec-new.flac" in merged
    assert "rec-old.flac" not in merged
    assert "New pipeline output." in merged
    # Empty-Agenda stub -> no Pre-Meeting Notes appendix.
    assert "## Pre-Meeting Notes" not in merged

    # Old recording's artifacts still present on disk (#33 leaves orphans
    # for #39 to clean up).
    assert old_audio.exists()
    assert old_sidecar.exists()
    # New recording's audio is also still present.
    assert new_audio.exists()


# ---------------------------------------------------------------------------
# Scenario 4: retry after partial-success crash heals orphans.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_retry_after_partial_success_heals_orphans(attach_client):
    """Simulate a crash AFTER the merged-note write + sidecar rebind but
    BEFORE the EventIndex synthetic-entry remove + unscheduled note unlink.

    Pre-state on disk (mid-crash):
      - Calendar stub at Clients/D/Meetings/<stub>.md with frontmatter
        ``event-id: E1`` AND ``recording: rec.flac``.
      - Sidecar (rec.recording.json) with ``event_id == "E1"`` and
        ``note_path`` pointing at the calendar stub.
      - Orphan unscheduled note still present at Clients/D/Meetings/u.md
        with frontmatter ``event-id: unscheduled:abc`` and the same
        ``recording: rec.flac`` (so the orphan-discovery scan keys on it).
      - EventIndex still contains a synthetic entry for ``unscheduled:abc``.

    POST attach-event for E1 -> 200, noop=true, cleanup_performed=true.
    After the call:
      - Orphan unscheduled note file deleted.
      - EventIndex synthetic entry gone.
      - Calendar stub on disk untouched (no second merge write).

    Re-POST -> 200, noop=true, cleanup_performed=false (idempotent retry
    on an already-clean state stays a clean no-op).
    """
    client, daemon = attach_client
    vault = daemon.config.vault_path

    # 1. Calendar stub (mid-crash state with `recording: rec.flac`).
    stub_rel = pathlib.Path("Clients/D/Meetings/2026-04-24 - sprint.md")
    stub_fm = {
        "date": "2026-04-24",
        "time": "14:00-15:00",
        "title": "Sprint",
        "event-id": "E1",
        "calendar-source": "google",
        "meeting-link": "https://meet.google.com/xyz",
        "org": "d",
        "org-subfolder": "Clients/D",
        "participants": [],
        "recording": "rec.flac",
        "pipeline-status": "complete",
    }
    stub_body_pre = "# Meeting Summary\n\nMerged pipeline output."
    stub_path = vault / stub_rel
    stub_path.parent.mkdir(parents=True, exist_ok=True)
    stub_path.write_text(
        "---\n" + yaml.dump(stub_fm, sort_keys=False) + "---\n\n" + stub_body_pre,
        encoding="utf-8",
    )
    daemon.event_index.add("E1", stub_rel, "d")

    # Snapshot stub bytes for untouched-assertion.
    stub_pre_bytes = stub_path.read_bytes()

    # 2. Sidecar already rebound to E1 (step 9 ran successfully).
    from recap.artifacts import (
        RecordingMetadata, load_recording_metadata, write_recording_metadata,
    )
    from recap.models import Participant
    audio = daemon.config.recordings_path / "rec.flac"
    audio.touch()
    md = RecordingMetadata(
        org="d", note_path=stub_rel.as_posix(),
        title="Sprint", date="2026-04-24",
        participants=[Participant(name="Alice")], platform="manual",
    )
    md.event_id = "E1"
    write_recording_metadata(audio, md)

    # 3. Orphan unscheduled note + synthetic EventIndex entry.
    orphan_rel = pathlib.Path("Clients/D/Meetings/u.md")
    orphan_path = vault / orphan_rel
    orphan_fm = {
        "event-id": "unscheduled:abc",
        "org": "d",
        "org-subfolder": "Clients/D",
        "date": "2026-04-24",
        "time": "14:30-15:15",
        "recording": "rec.flac",
    }
    orphan_path.write_text(
        "---\n" + yaml.dump(orphan_fm, sort_keys=False) + "---\n\nOrphan body.",
        encoding="utf-8",
    )
    daemon.event_index.add(
        "unscheduled:abc", orphan_rel, "d",
    )

    # First POST -- should heal orphans.
    resp = await client.post(
        "/api/recordings/rec/attach-event",
        json={"event_id": "E1"},
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200
    data = await resp.json()
    assert data["status"] == "ok"
    assert data["noop"] is True
    assert data["cleanup_performed"] is True

    # Orphan note file removed.
    assert not orphan_path.exists()
    # Synthetic EventIndex entry removed.
    assert daemon.event_index.lookup("unscheduled:abc") is None
    # E1 still indexed.
    assert daemon.event_index.lookup("E1") is not None
    # Calendar stub on disk untouched (no second merge write).
    assert stub_path.read_bytes() == stub_pre_bytes
    # Sidecar still bound to E1.
    loaded = load_recording_metadata(audio)
    assert loaded is not None
    assert loaded.event_id == "E1"

    # Second POST on already-clean state -- still a no-op, no cleanup needed.
    resp2 = await client.post(
        "/api/recordings/rec/attach-event",
        json={"event_id": "E1"},
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp2.status == 200
    data2 = await resp2.json()
    assert data2["status"] == "ok"
    assert data2["noop"] is True
    assert data2["cleanup_performed"] is False
    # Stub still untouched after the second call.
    assert stub_path.read_bytes() == stub_pre_bytes
