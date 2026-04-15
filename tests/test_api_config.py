"""Tests for /api/config GET + DTO translation (Phase 4 Task 8)."""
from __future__ import annotations

import pathlib

import pytest
from ruamel.yaml.comments import CommentedMap

from recap.daemon.api_config import (
    api_config_to_json_dict,
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
            "vault_path: /v\n"
            "recordings_path: /r\n"
            "user_name: Tim\n"
            "orgs:\n"
            "  - name: alpha\n"
            "    subfolder: Clients/Alpha\n"
            "    default: true\n"
            "  - name: beta\n"
            "    subfolder: Clients/Beta\n"
            "    default: false\n"
            "detection:\n"
            "  google_meet:\n"
            "    enabled: true\n"
            "    behavior: prompt\n"
            "calendar:\n"
            "  google:\n"
            "    enabled: true\n"
            "    calendar_id: primary\n"
            "    org: alpha\n"
            "known_contacts:\n"
            "  - name: Jane\n"
            "    aliases: [J]\n"
            "    email: j@example.com\n"
            "recording:\n"
            "  silence_timeout_minutes: 4\n"
            "  max_duration_hours: 2\n"
            "logging:\n"
            "  retention_days: 14\n"
            "daemon_ports:\n"
            "  plugin_port: 9900\n",
            encoding="utf-8",
        )
        api = yaml_doc_to_api_config(load_yaml_doc(config_path))

        assert api.vault_path == "/v"
        assert api.recordings_path == "/r"
        assert api.user_name == "Tim"
        assert api.plugin_port == 9900
        assert len(api.orgs) == 2
        assert api.orgs[0].name == "alpha"
        assert api.orgs[0].default is True
        assert api.orgs[1].name == "beta"
        assert api.default_org == "alpha"
        assert "google_meet" in api.detection
        assert api.detection["google_meet"].behavior == "prompt"
        assert api.calendar["google"].calendar_id == "primary"
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
            "vault_path: /v\n"
            "recordings_path: /r\n"
            "orgs:\n"
            "  - name: alpha\n"
            "    subfolder: A\n"
            "  - name: beta\n"
            "    subfolder: B\n",
            encoding="utf-8",
        )
        api = yaml_doc_to_api_config(load_yaml_doc(config_path))
        assert api.default_org is None


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
