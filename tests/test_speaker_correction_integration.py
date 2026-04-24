"""End-to-end #28 scenarios.

Combines: plugin POST (simulated via authed aiohttp client) -> daemon
write -> reprocess stub -> frontmatter refresh (simulated). Stubs the
LLM / analyze stage but runs the real ``_apply_speaker_mapping`` +
``_build_effective_participants`` + vault writer so the full correction
round-trip is exercised.
"""
from __future__ import annotations

import asyncio
import json
import pathlib
from datetime import date, datetime, timedelta, timezone

import pytest
import pytest_asyncio
import yaml

from recap.artifacts import save_transcript, speakers_path
from recap.daemon.server import create_app
from recap.daemon.service import Daemon
from recap.models import (
    MeetingMetadata,
    Participant,
    TranscriptResult,
    Utterance,
)
from recap.pipeline import (
    _apply_speaker_mapping,
    _build_effective_participants,
)
from tests.conftest import AUTH_TOKEN, make_daemon_config


# ---------------------------------------------------------------------------
# Fixture: real Daemon + authed client + trigger_calls recorder.
#
# Mirrors tests/test_daemon_server.py::speakers_post_client but defined
# locally so this module is self-contained and can seed custom YAML (e.g.
# pre-existing known-contacts) when a test needs it.
# ---------------------------------------------------------------------------


_CONFIG_YAML_TEMPLATE = """\
# Top-of-file marker comment (do not remove)
config-version: 1
vault-path: "{vault}"
recordings-path: "{rec}"
user-name: "TestUser"
orgs:
  alpha:
    subfolder: Clients/Alpha
    llm-backend: claude
    default: true
  beta:
    subfolder: Clients/Beta
    llm-backend: claude
detection:
  teams:
    enabled: true
    behavior: auto-record
  zoom:
    enabled: true
    behavior: auto-record
  signal:
    enabled: true
    behavior: prompt
calendars: {{}}
known-contacts:{contacts}
recording:
  silence-timeout-minutes: 5
  max-duration-hours: 3
logging:
  retention-days: 7
daemon:
  plugin-port: 9847
"""


def _render_config_yaml(
    vault: pathlib.Path,
    rec: pathlib.Path,
    contacts_yaml: str = " []",
) -> str:
    """Render the test config.yaml with optional pre-seeded known-contacts.

    ``contacts_yaml`` is inlined directly after the ``known-contacts:`` key.
    Pass " []" (default) for an empty list, or a leading-newline YAML block
    like "\\n  - name: Alice\\n    display-name: Alice" to seed entries.
    """
    return _CONFIG_YAML_TEMPLATE.format(
        vault=vault.as_posix(),
        rec=rec.as_posix(),
        contacts=contacts_yaml,
    )


async def _build_client(aiohttp_client, tmp_path, contacts_yaml=" []"):
    """Build ``(client, daemon, trigger_calls)`` with an optional pre-seeded
    known-contacts block in config.yaml."""
    cfg = make_daemon_config(tmp_path)
    config_path = tmp_path / "config.yaml"
    config_path.write_text(
        _render_config_yaml(
            tmp_path / "vault", tmp_path / "rec", contacts_yaml=contacts_yaml,
        ),
        encoding="utf-8",
    )
    daemon = Daemon(cfg, config_path=config_path)
    daemon.started_at = (
        datetime.now(timezone.utc).astimezone() - timedelta(seconds=5)
    )

    trigger_calls: list[tuple] = []

    async def _trigger(rec_path, org, from_stage):
        trigger_calls.append((rec_path, org, from_stage))

    app = create_app(auth_token=AUTH_TOKEN, pipeline_trigger=_trigger)
    app["daemon"] = daemon
    client = await aiohttp_client(app)
    return client, daemon, trigger_calls


@pytest_asyncio.fixture
async def speakers_post_client(aiohttp_client, tmp_path):
    """Default fixture: empty ``known-contacts``. Tests that need a
    pre-seeded contacts list call ``_build_client`` directly."""
    return await _build_client(aiohttp_client, tmp_path)


def _seed_recording_with_transcript(
    daemon: Daemon,
    *,
    stem: str = "rec",
    utterances: list[Utterance] | None = None,
) -> pathlib.Path:
    """Seed a zero-byte .flac + matching .transcript.json so the POST
    handler's ``validate_from_stage('analyze')`` call succeeds.

    Mirrors ``tests/test_daemon_server.py::_seed_recording_with_transcript``
    but lets callers provide a custom utterance list so the transcript
    models the scenario under test.
    """
    audio = daemon.config.recordings_path / f"{stem}.flac"
    audio.touch()
    if utterances is None:
        utterances = [
            Utterance(
                speaker_id="SPEAKER_00",
                speaker="SPEAKER_00",
                start=0.0,
                end=1.0,
                text="hi",
            ),
        ]
    save_transcript(
        audio,
        TranscriptResult(
            utterances=utterances,
            raw_text=" ".join(u.text for u in utterances),
            language="en",
        ),
    )
    return audio


# ---------------------------------------------------------------------------
# Scenario 1: unresolved speaker -> new contact + stub + frontmatter refresh
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_unresolved_creates_contact_stub_and_maps(
    speakers_post_client,
):
    """AC #1, #3: unresolved SPEAKER_00 -> Alice with new contact creation.

    After POST:
      - .speakers.json written keyed by speaker_id
      - known-contacts has {name: Alice, display-name: Alice, ...}
      - daemon.config reflects Alice after refresh
      - People stub created at Clients/Alpha/People/Alice.md via
        canonical _generate_person_stub template
      - Pipeline trigger called with (audio_path, org, 'analyze')
      - Running the real _apply_speaker_mapping + _build_effective_participants
        against the seeded transcript rewrites SPEAKER_00 -> Alice and
        surfaces Alice as the effective participant (frontmatter refresh).
    """
    client, daemon, trigger_calls = speakers_post_client
    audio = _seed_recording_with_transcript(daemon)

    resp = await client.post(
        "/api/meetings/speakers",
        json={
            "stem": "rec",
            "mapping": {"SPEAKER_00": "Alice"},
            "org": "alpha",
            "contact_mutations": [
                {
                    "action": "create",
                    "name": "Alice",
                    "display_name": "Alice",
                    "email": "alice@example.com",
                },
            ],
        },
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200
    body = await resp.json()
    assert body["status"] == "processing"

    # .speakers.json written next to the audio, keyed by speaker_id.
    sp_path = speakers_path(audio)
    assert sp_path.exists()
    assert json.loads(sp_path.read_text()) == {"SPEAKER_00": "Alice"}

    # known-contacts on disk contains Alice with the email.
    doc = yaml.safe_load(daemon.config_path.read_text())
    contacts = doc["known-contacts"]
    assert any(
        c.get("name") == "Alice"
        and c.get("display-name") == "Alice"
        and c.get("email") == "alice@example.com"
        for c in contacts
    )

    # daemon.refresh_config() picked up the new contact.
    assert any(
        kc.name == "Alice" and kc.email == "alice@example.com"
        for kc in daemon.config.known_contacts
    )

    # People stub created under the alpha org subfolder using the canonical
    # template (Key Topics + Meeting History sections from _generate_person_stub).
    stub_path = (
        daemon.config.vault_path / "Clients" / "Alpha" / "People" / "Alice.md"
    )
    assert stub_path.exists()
    stub_text = stub_path.read_text(encoding="utf-8")
    assert "## Key Topics" in stub_text
    assert "## Meeting History" in stub_text

    # Pipeline trigger invoked with the analyze stage.
    await asyncio.sleep(0)  # let create_task run
    assert len(trigger_calls) == 1
    rec_path, org, from_stage = trigger_calls[0]
    assert rec_path == audio
    assert org == "alpha"
    assert from_stage == "analyze"

    # Real _apply_speaker_mapping rewrites speaker labels keyed on speaker_id.
    from recap.artifacts import load_transcript

    transcript = load_transcript(audio)
    mapping = json.loads(sp_path.read_text())
    mapped = _apply_speaker_mapping(transcript, mapping)
    assert mapped.utterances[0].speaker == "Alice"
    assert mapped.utterances[0].speaker_id == "SPEAKER_00"

    # Real _build_effective_participants picks up Alice as a correction-derived
    # participant (empty enrichment roster + eligible display label).
    metadata = MeetingMetadata(
        title="Test",
        date=date(2026, 4, 23),
        participants=[],
        platform="manual",
    )
    effective = _build_effective_participants(
        metadata, mapped, daemon.config.known_contacts,
    )
    assert [p.name for p in effective] == ["Alice"]


# ---------------------------------------------------------------------------
# Scenario 2: already-named speaker -> add alias to existing contact
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_correct_already_named_adds_alias(aiohttp_client, tmp_path):
    """Correcting an already-named speaker ('alice') to existing contact
    'Alice Mooney' adds the typed name as an alias on the canonical entry.

    Seeds config.yaml with Alice Mooney already in known-contacts, then
    posts an add_alias mutation that attaches 'alice' as an alias.
    Verifies the alias persists in config.yaml via ruamel round-trip
    and that daemon.config.known_contacts reflects it after refresh.
    """
    contacts_yaml = (
        "\n"
        "  - name: Alice Mooney\n"
        "    display-name: Alice Mooney\n"
        "    email: alice@mooney.test\n"
    )
    client, daemon, trigger_calls = await _build_client(
        aiohttp_client, tmp_path, contacts_yaml=contacts_yaml,
    )
    audio = _seed_recording_with_transcript(
        daemon,
        utterances=[
            Utterance(
                speaker_id="SPEAKER_00",
                speaker="alice",
                start=0.0,
                end=1.0,
                text="hi",
            ),
        ],
    )

    resp = await client.post(
        "/api/meetings/speakers",
        json={
            "stem": "rec",
            "mapping": {"SPEAKER_00": "Alice Mooney"},
            "org": "alpha",
            "contact_mutations": [
                {
                    "action": "add_alias",
                    "name": "Alice Mooney",
                    "alias": "alice",
                },
            ],
        },
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200

    # Alias persists in config.yaml under the canonical Alice Mooney entry.
    doc = yaml.safe_load(daemon.config_path.read_text())
    alice = next(
        c for c in doc["known-contacts"] if c.get("name") == "Alice Mooney"
    )
    assert "alice" in (alice.get("aliases") or [])

    # daemon.config reflects the alias after refresh_config.
    live = next(
        kc for kc in daemon.config.known_contacts if kc.name == "Alice Mooney"
    )
    assert "alice" in live.aliases

    # .speakers.json points the speaker_id at the canonical name.
    sp_path = speakers_path(audio)
    assert json.loads(sp_path.read_text()) == {"SPEAKER_00": "Alice Mooney"}

    # Trigger fired with analyze.
    await asyncio.sleep(0)
    assert len(trigger_calls) == 1
    assert trigger_calls[0] == (audio, "alpha", "analyze")


# ---------------------------------------------------------------------------
# Scenario 3: legacy .speakers.json (display-label keyed) is a silent no-op
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_legacy_speakers_json_is_no_op(speakers_post_client):
    """Pre-#28 .speakers.json (display-label keyed) doesn't crash or
    accidentally apply. First post-#28 save rewrites keyed by speaker_id.

    The replay guarantee is covered in test_pipeline_speaker_mapping.py
    at the unit level. This test covers the round-trip: a legacy file
    sitting on disk, then a new correction overwrites it cleanly keyed
    by speaker_id.
    """
    client, daemon, trigger_calls = speakers_post_client
    audio = _seed_recording_with_transcript(daemon)

    # Seed a legacy .speakers.json keyed by the old display-label convention
    # (pre-#28 clients wrote the current ``speaker`` field, not ``speaker_id``).
    sp_path = speakers_path(audio)
    sp_path.write_text(json.dumps({"some_legacy_label": "StaleName"}, indent=2))

    # Verify the replay-on-load behavior documented in _apply_speaker_mapping:
    # legacy keys don't match any speaker_id, so the transcript is unchanged.
    from recap.artifacts import load_transcript

    transcript = load_transcript(audio)
    legacy_mapping = json.loads(sp_path.read_text())
    replayed = _apply_speaker_mapping(transcript, legacy_mapping)
    assert replayed.utterances[0].speaker == "SPEAKER_00"  # unchanged
    assert replayed.utterances[0].speaker_id == "SPEAKER_00"

    # Post a new correction with speaker_id keys.
    resp = await client.post(
        "/api/meetings/speakers",
        json={
            "stem": "rec",
            "mapping": {"SPEAKER_00": "Carol"},
            "org": "alpha",
        },
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200

    # File was overwritten — legacy key is gone, only the new speaker_id key remains.
    on_disk = json.loads(sp_path.read_text())
    assert on_disk == {"SPEAKER_00": "Carol"}
    assert "some_legacy_label" not in on_disk

    # Trigger invoked from analyze.
    await asyncio.sleep(0)
    assert len(trigger_calls) == 1
    assert trigger_calls[0] == (audio, "alpha", "analyze")


# ---------------------------------------------------------------------------
# Scenario 4: create mutation persists across sessions (alias resolution works)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_cross_session_alias_persists(speakers_post_client):
    """After a create + alias round-trip, the contact is visible in
    daemon.config.known_contacts for subsequent meetings.

    Posts two sequential mutations: create 'Sean Mooney' then add_alias
    'Sean M.'. Verifies both land on disk and in live config, then
    simulates a subsequent match_known_contacts call to confirm alias
    resolution against the newly-added contact succeeds.
    """
    client, daemon, trigger_calls = speakers_post_client
    audio = _seed_recording_with_transcript(daemon)

    # First save: create Sean Mooney (fresh contact).
    resp = await client.post(
        "/api/meetings/speakers",
        json={
            "stem": "rec",
            "mapping": {"SPEAKER_00": "Sean Mooney"},
            "org": "alpha",
            "contact_mutations": [
                {
                    "action": "create",
                    "name": "Sean Mooney",
                    "display_name": "Sean Mooney",
                    "email": "sean@mooney.test",
                },
            ],
        },
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200

    # Second save: attach 'Sean M.' as an alias on the canonical entry.
    resp = await client.post(
        "/api/meetings/speakers",
        json={
            "stem": "rec",
            "mapping": {"SPEAKER_00": "Sean Mooney"},
            "org": "alpha",
            "contact_mutations": [
                {
                    "action": "add_alias",
                    "name": "Sean Mooney",
                    "alias": "Sean M.",
                },
            ],
        },
        headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
    )
    assert resp.status == 200

    # daemon.config reflects both the new contact and the alias after refresh.
    sean = next(
        kc for kc in daemon.config.known_contacts if kc.name == "Sean Mooney"
    )
    assert sean.email == "sean@mooney.test"
    assert "Sean M." in sean.aliases

    # Simulate a subsequent meeting: alias resolution via match_known_contacts
    # now recognizes 'Sean M.' and canonicalizes to 'Sean Mooney'.
    from recap.daemon.recorder.enrichment import match_known_contacts

    observed = [Participant(name="Sean M.")]
    canonical = match_known_contacts(observed, daemon.config.known_contacts)
    assert len(canonical) == 1
    assert canonical[0].name == "Sean Mooney"
    # The canonical contact's email is attached on match (even though the
    # observed participant had none).
    assert canonical[0].email == "sean@mooney.test"

    # Real _build_effective_participants on a second meeting that observed
    # the alias re-canonicalizes via live contacts — proving the alias edit
    # flows through to downstream frontmatter without a daemon restart.
    second_metadata = MeetingMetadata(
        title="Second Meeting",
        date=date(2026, 4, 24),
        participants=[Participant(name="Sean M.")],
        platform="manual",
    )
    # Empty transcript — we only care about enrichment canonicalization here.
    empty_transcript = TranscriptResult(utterances=[], raw_text="", language="en")
    effective = _build_effective_participants(
        second_metadata, empty_transcript, daemon.config.known_contacts,
    )
    assert [p.name for p in effective] == ["Sean Mooney"]

    # Both saves dispatched a reprocess.
    await asyncio.sleep(0)
    assert len(trigger_calls) == 2
    assert all(c[2] == "analyze" for c in trigger_calls)
    assert all(c[0] == audio for c in trigger_calls)
