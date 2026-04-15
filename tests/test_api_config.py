"""Tests for /api/config GET + PATCH + DTO translation (Phase 4 Tasks 8-9)."""
from __future__ import annotations

import pathlib

import pytest
from ruamel.yaml.comments import CommentedMap

from recap.daemon.api_config import (
    api_config_to_json_dict,
    apply_api_patch_to_yaml_doc,
    dump_yaml_doc,
    find_unknown_keys,
    load_yaml_doc,
    yaml_doc_to_api_config,
)
from tests.conftest import AUTH_TOKEN


# ---------------------------------------------------------------------------
# Pure module tests (no aiohttp)
# ---------------------------------------------------------------------------

class TestYamlDocLoad:
    def test_load_preserves_comments(self, tmp_path: pathlib.Path) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "# Important top comment\n"
            "vault_path: /vault\n"
            "recordings_path: /rec\n"
            "# inline-style comment\n"
            "user_name: Alice\n",
            encoding="utf-8",
        )
        doc = load_yaml_doc(config_path)
        assert isinstance(doc, CommentedMap)
        assert doc["vault_path"] == "/vault"
        assert doc["user_name"] == "Alice"

    def test_load_empty_file_returns_empty_map(
        self, tmp_path: pathlib.Path,
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("", encoding="utf-8")
        doc = load_yaml_doc(config_path)
        assert isinstance(doc, CommentedMap)
        assert len(doc) == 0

    def test_load_non_mapping_root_raises(
        self, tmp_path: pathlib.Path,
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text("- not\n- a\n- mapping\n", encoding="utf-8")
        with pytest.raises(ValueError, match="must be a mapping"):
            load_yaml_doc(config_path)


class TestYamlDocToApiConfig:
    def test_returns_allowlisted_fields(
        self, tmp_path: pathlib.Path,
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "auth_token: secret-must-not-leak\n"
            "config-version: 1\n"
            "vault-path: /v\n"
            "recordings-path: /r\n"
            "user-name: Tim\n"
            "orgs:\n"
            "  alpha:\n"
            "    subfolder: Clients/Alpha\n"
            "    llm-backend: claude\n"
            "    default: true\n"
            "  beta:\n"
            "    subfolder: Clients/Beta\n"
            "    llm-backend: claude\n"
            "detection:\n"
            "  teams:\n"
            "    enabled: true\n"
            "    behavior: prompt\n"
            "    default-org: alpha\n"
            "calendars:\n"
            "  google:\n"
            "    calendar-id: primary\n"
            "    org: alpha\n"
            "known-contacts:\n"
            "  - name: Jane\n"
            "    display-name: Jane S.\n"
            "recording:\n"
            "  silence-timeout-minutes: 4\n"
            "  max-duration-hours: 2\n"
            "logging:\n"
            "  retention-days: 14\n"
            "daemon:\n"
            "  plugin-port: 9900\n",
            encoding="utf-8",
        )
        api = yaml_doc_to_api_config(load_yaml_doc(config_path))

        assert api.vault_path == "/v"
        assert api.recordings_path == "/r"
        assert api.user_name == "Tim"
        assert api.plugin_port == 9900
        assert len(api.orgs) == 2
        names = [o.name for o in api.orgs]
        assert names == ["alpha", "beta"]
        assert api.orgs[0].default is True
        assert api.orgs[1].default is False
        assert api.default_org == "alpha"
        assert "teams" in api.detection
        assert api.detection["teams"].behavior == "prompt"
        assert api.detection["teams"].default_org == "alpha"
        assert api.calendar["google"].calendar_id == "primary"
        assert api.calendar["google"].org == "alpha"
        assert api.known_contacts[0].name == "Jane"
        assert api.recording_silence_timeout_minutes == 4
        assert api.recording_max_duration_hours == 2.0
        assert api.logging_retention_days == 14

        # Secrets never leak through the DTO.
        as_dict = api_config_to_json_dict(api)
        assert "auth_token" not in as_dict
        assert "auth_token" not in dir(api)

    def test_default_org_none_when_no_default_flag(
        self, tmp_path: pathlib.Path,
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "config-version: 1\n"
            "vault-path: /v\n"
            "recordings-path: /r\n"
            "orgs:\n"
            "  alpha:\n"
            "    subfolder: A\n"
            "  beta:\n"
            "    subfolder: B\n",
            encoding="utf-8",
        )
        api = yaml_doc_to_api_config(load_yaml_doc(config_path))
        assert api.default_org is None

    def test_dto_reads_real_config_example(self) -> None:
        """Regression guard for the kebab/snake + dict/list translation.

        Ensures ``yaml_doc_to_api_config`` projects populated fields
        against the repo's real ``config.example.yaml`` shape (the
        template new users copy), not just the synthetic test fixture.
        """
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        example = repo_root / "config.example.yaml"
        api = yaml_doc_to_api_config(load_yaml_doc(example))

        assert api.vault_path != ""
        assert api.recordings_path != ""
        assert api.user_name is not None
        assert api.plugin_port == 9847
        assert len(api.orgs) >= 1
        assert any(o.default for o in api.orgs)
        assert api.default_org is not None


# ---------------------------------------------------------------------------
# HTTP surface
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestApiConfigGet:
    async def test_returns_sanitized_config(self, daemon_client) -> None:
        client, daemon = daemon_client
        # Inject a secret into the on-disk file; it must NOT appear in the
        # API response.
        config_path = daemon.config_path
        content = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            "auth_token: must-not-leak\n" + content, encoding="utf-8",
        )

        resp = await client.get(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert "vault_path" in body
        assert "plugin_port" in body
        assert "auth_token" not in body
        assert body["default_org"] == "alpha"

    async def test_requires_bearer(self, daemon_client) -> None:
        client, _ = daemon_client
        resp = await client.get("/api/config")
        assert resp.status == 401

    async def test_missing_config_path_returns_503(
        self, daemon_client,
    ) -> None:
        client, daemon = daemon_client
        daemon.config_path = None
        resp = await client.get(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
        )
        assert resp.status == 503


# ---------------------------------------------------------------------------
# PATCH — ruamel round-trip
# ---------------------------------------------------------------------------

def _yaml_with(*extra_lines: str) -> str:
    base = (
        "# Important top comment\n"
        "vault_path: /v\n"
        "recordings_path: /r\n"
    )
    return base + "".join(line + "\n" for line in extra_lines)


def _dump_to_string(doc: CommentedMap) -> str:
    import io
    buf = io.StringIO()
    dump_yaml_doc(doc, buf)
    return buf.getvalue()


class TestApplyPatchToYamlDoc:
    def test_scalar_patch_preserves_sibling_comments(
        self, tmp_path: pathlib.Path,
    ) -> None:
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "# Important comment\n"
            "vault-path: /old\n"
            "# Another comment\n"
            "recordings-path: /r\n",
            encoding="utf-8",
        )
        doc = load_yaml_doc(config_path)
        apply_api_patch_to_yaml_doc(doc, {"vault_path": "/new"})
        dumped = _dump_to_string(doc)
        assert "/new" in dumped
        assert "vault-path" in dumped
        assert "# Important comment" in dumped
        assert "# Another comment" in dumped

    def test_orgs_patch_translates_list_to_dict_and_preserves_llm_backend(
        self, tmp_path: pathlib.Path,
    ) -> None:
        """Whole-list replacement, translated to dict-keyed-by-name, and
        ``llm-backend`` preserved on orgs that match by name.
        """
        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "config-version: 1\n"
            "vault-path: /v\n"
            "recordings-path: /r\n"
            "orgs:\n"
            "  alpha:\n"
            "    subfolder: A\n"
            "    llm-backend: custom-backend\n"
            "    default: true\n"
            "  beta:\n"
            "    subfolder: B\n"
            "    llm-backend: claude\n",
            encoding="utf-8",
        )
        doc = load_yaml_doc(config_path)
        apply_api_patch_to_yaml_doc(
            doc,
            {
                "orgs": [
                    {
                        "name": "alpha", "subfolder": "A-new",
                        "default": True,
                    },
                    {
                        "name": "gamma", "subfolder": "G",
                        "default": False,
                    },
                ],
            },
        )
        # Whole-list replacement: beta is gone.
        assert "beta" not in doc["orgs"]
        # alpha kept its custom llm-backend.
        assert doc["orgs"]["alpha"]["subfolder"] == "A-new"
        assert doc["orgs"]["alpha"]["llm-backend"] == "custom-backend"
        assert doc["orgs"]["alpha"]["default"] is True
        # gamma is new; no llm-backend key written (loader defaults).
        assert doc["orgs"]["gamma"]["subfolder"] == "G"
        assert "llm-backend" not in doc["orgs"]["gamma"]


class TestRealLoaderRoundTrip:
    """Every successful PATCH must leave a doc the real daemon loader
    can still read. Phase 4 review caught this as a P1 gap.
    """

    def test_plugin_port_patch_survives_real_loader(
        self, tmp_path: pathlib.Path,
    ) -> None:
        import io

        from recap.daemon.api_config import dump_yaml_doc
        from recap.daemon.config import load_daemon_config

        repo_root = pathlib.Path(__file__).resolve().parent.parent
        example = repo_root / "config.example.yaml"
        doc = load_yaml_doc(example)
        apply_api_patch_to_yaml_doc(doc, {"plugin_port": 9999})

        out_path = tmp_path / "config.yaml"
        with out_path.open("w", encoding="utf-8") as f:
            dump_yaml_doc(doc, f)

        reloaded = load_daemon_config(out_path)
        assert reloaded.daemon_ports.plugin_port == 9999

    def test_orgs_patch_survives_real_loader(
        self, tmp_path: pathlib.Path,
    ) -> None:
        import io

        from recap.daemon.api_config import dump_yaml_doc
        from recap.daemon.config import load_daemon_config

        repo_root = pathlib.Path(__file__).resolve().parent.parent
        example = repo_root / "config.example.yaml"
        doc = load_yaml_doc(example)
        apply_api_patch_to_yaml_doc(
            doc,
            {
                "orgs": [
                    {
                        "name": "new-org", "subfolder": "_Recap/New",
                        "default": True,
                    },
                ],
            },
        )

        out_path = tmp_path / "config.yaml"
        with out_path.open("w", encoding="utf-8") as f:
            dump_yaml_doc(doc, f)

        reloaded = load_daemon_config(out_path)
        assert len(reloaded.orgs) == 1
        assert reloaded.orgs[0].name == "new-org"
        assert reloaded.orgs[0].subfolder == "_Recap/New"
        assert reloaded.orgs[0].default is True


class TestValidateYamlDoc:
    def test_accepts_fixture_shape(self, tmp_path: pathlib.Path) -> None:
        from recap.daemon.api_config import validate_yaml_doc

        repo_root = pathlib.Path(__file__).resolve().parent.parent
        example = repo_root / "config.example.yaml"
        doc = load_yaml_doc(example)
        # Real config loads through the canonical parser without raising.
        validate_yaml_doc(doc)

    def test_rejects_config_with_missing_vault_path(
        self, tmp_path: pathlib.Path,
    ) -> None:
        from recap.daemon.api_config import validate_yaml_doc

        config_path = tmp_path / "config.yaml"
        config_path.write_text(
            "config-version: 1\n"
            "recordings-path: /r\n",
            encoding="utf-8",
        )
        doc = load_yaml_doc(config_path)
        with pytest.raises(ValueError, match="vault-path"):
            validate_yaml_doc(doc)


class TestFindUnknownKeys:
    def test_top_level_unknown_key(self) -> None:
        assert find_unknown_keys({"nope": 1}) == ["nope"]

    def test_nested_detection_unknown_subfield_caught(self) -> None:
        out = find_unknown_keys(
            {"detection": {"google_meet": {"enabled": True, "bogus": 1}}},
        )
        assert "detection.google_meet.bogus" in out

    def test_orgs_entry_unknown_field(self) -> None:
        out = find_unknown_keys(
            {
                "orgs": [
                    {
                        "name": "x", "subfolder": "y",
                        "default": True, "zzz": "nope",
                    },
                ],
            },
        )
        assert "orgs[].zzz" in out

    def test_calendar_entry_unknown_field(self) -> None:
        out = find_unknown_keys(
            {"calendar": {"google": {"enabled": True, "nope": "x"}}},
        )
        assert "calendar.google.nope" in out

    def test_known_contacts_entry_unknown_field(self) -> None:
        out = find_unknown_keys(
            {"known_contacts": [{"name": "X", "bad": "y"}]},
        )
        assert "known_contacts[].bad" in out

    def test_default_org_flagged_as_read_only(self) -> None:
        out = find_unknown_keys({"default_org": "alpha"})
        assert any("default_org" in entry for entry in out)

    def test_allowed_top_level_key_not_flagged(self) -> None:
        assert find_unknown_keys({"vault_path": "/v"}) == []

    def test_orgs_not_a_list_returns_error(self) -> None:
        out = find_unknown_keys({"orgs": "oops"})
        assert any("orgs" in e and "list" in e for e in out)

    def test_detection_not_a_dict_returns_error(self) -> None:
        out = find_unknown_keys({"detection": "oops"})
        assert any("detection" in e and "object" in e for e in out)

    def test_calendar_not_a_dict_returns_error(self) -> None:
        out = find_unknown_keys({"calendar": "oops"})
        assert any("calendar" in e and "object" in e for e in out)

    def test_known_contacts_not_a_list_returns_error(self) -> None:
        out = find_unknown_keys({"known_contacts": "oops"})
        assert any("known_contacts" in e and "list" in e for e in out)

    def test_orgs_entry_not_a_dict_returns_error(self) -> None:
        out = find_unknown_keys({"orgs": ["oops", {"name": "x"}]})
        assert any("orgs[0]" in e and "object" in e for e in out)

    def test_detection_rule_not_a_dict_returns_error(self) -> None:
        out = find_unknown_keys({"detection": {"teams": "oops"}})
        assert any("detection.teams" in e and "object" in e for e in out)

    def test_calendar_entry_not_a_dict_returns_error(self) -> None:
        out = find_unknown_keys({"calendar": {"google": "oops"}})
        assert any("calendar.google" in e and "object" in e for e in out)

    def test_known_contacts_entry_not_a_dict_returns_error(self) -> None:
        out = find_unknown_keys({"known_contacts": ["oops"]})
        assert any(
            "known_contacts[0]" in e and "object" in e for e in out
        )


@pytest.mark.asyncio
class TestApiConfigPatch:
    async def test_patch_updates_config_yaml_and_preserves_comments(
        self, daemon_client,
    ) -> None:
        client, daemon = daemon_client
        config_path = daemon.config_path
        # Prepend an extra marker comment we can look for after the PATCH.
        original = config_path.read_text(encoding="utf-8")
        config_path.write_text(
            "# MARKER-COMMENT-123\n" + original, encoding="utf-8",
        )

        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={"user_name": "NewName"},
        )
        assert resp.status == 200
        body = await resp.json()
        assert body.get("restart_required") is True

        after = config_path.read_text(encoding="utf-8")
        assert "NewName" in after
        assert "# MARKER-COMMENT-123" in after

    async def test_patch_unknown_top_level_key_returns_400(
        self, daemon_client,
    ) -> None:
        client, _ = daemon_client
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={"nonsense_field": True},
        )
        assert resp.status == 400

    async def test_patch_unknown_nested_key_returns_400(
        self, daemon_client,
    ) -> None:
        client, _ = daemon_client
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={
                "detection": {
                    "google_meet": {"enabled": True, "bogus_field": 1},
                },
            },
        )
        assert resp.status == 400

    async def test_patch_default_org_rejected(self, daemon_client) -> None:
        client, _ = daemon_client
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={"default_org": "alpha"},
        )
        assert resp.status == 400

    async def test_patch_non_dict_body_returns_400(
        self, daemon_client,
    ) -> None:
        client, _ = daemon_client
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json=[1, 2, 3],
        )
        assert resp.status == 400

    async def test_patch_requires_bearer(self, daemon_client) -> None:
        client, _ = daemon_client
        resp = await client.patch("/api/config", json={"user_name": "X"})
        assert resp.status == 401

    async def test_patch_emits_config_updated_event(
        self, daemon_client,
    ) -> None:
        client, daemon = daemon_client
        before = len(daemon.event_journal.tail(limit=500))
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={"user_name": "Journaled"},
        )
        assert resp.status == 200
        events = daemon.event_journal.tail(limit=500)
        assert len(events) > before
        assert any(e.get("event") == "config_updated" for e in events)

    async def test_patch_missing_config_path_returns_503(
        self, daemon_client,
    ) -> None:
        client, daemon = daemon_client
        daemon.config_path = None
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json={"user_name": "X"},
        )
        assert resp.status == 503

    @pytest.mark.parametrize(
        "malformed_body",
        [
            {"orgs": "oops"},
            {"detection": "oops"},
            {"calendar": "oops"},
            {"known_contacts": "oops"},
            {"orgs": ["not-an-object"]},
            {"detection": {"teams": "oops"}},
            {"calendar": {"google": "oops"}},
            {"known_contacts": ["oops"]},
        ],
        ids=[
            "orgs-scalar",
            "detection-scalar",
            "calendar-scalar",
            "known_contacts-scalar",
            "orgs-entry-scalar",
            "detection-rule-scalar",
            "calendar-entry-scalar",
            "known_contacts-entry-scalar",
        ],
    )
    async def test_patch_malformed_shape_returns_400_not_500(
        self, daemon_client, malformed_body,
    ) -> None:
        """Regression for reviewer P1: malformed structured PATCH bodies
        must 400 before reaching ``apply_api_patch_to_yaml_doc`` so the
        doc on disk stays clean and the handler never 500s.
        """
        client, daemon = daemon_client
        before = daemon.config_path.read_text(encoding="utf-8")
        resp = await client.patch(
            "/api/config",
            headers={"Authorization": f"Bearer {AUTH_TOKEN}"},
            json=malformed_body,
        )
        assert resp.status == 400
        # File on disk must be unchanged after a rejected PATCH.
        after = daemon.config_path.read_text(encoding="utf-8")
        assert before == after
