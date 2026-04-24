"""Tests for _apply_contact_mutations (#28 Task 10)."""
from __future__ import annotations

import threading
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from recap.daemon.api_config import _apply_contact_mutations


def _fake_daemon(config_path: Path) -> MagicMock:
    """Minimal fake daemon with config_lock + config_path."""
    d = MagicMock()
    d.config_path = config_path
    d.config_lock = threading.Lock()
    return d


def _write_min_config(tmp_path: Path, contacts: list[dict] | None = None) -> Path:
    """Write a minimal valid config.yaml (kebab-case, dict-orgs on disk).

    Matches the on-disk shape consumed by ``parse_daemon_config_dict``:
    orgs is a dict keyed by slug, not a list; detection/calendars are
    kebab-case. Contacts are optional.
    """
    path = tmp_path / "config.yaml"
    doc = {
        "config-version": 1,
        "vault-path": str(tmp_path / "vault"),
        "recordings-path": str(tmp_path / "recordings"),
        "user-name": "Tester",
        "orgs": {
            "test": {
                "subfolder": "Test",
                "llm-backend": "claude",
                "default": True,
            },
        },
        "detection": {},
        "calendars": {},
    }
    if contacts is not None:
        doc["known-contacts"] = contacts
    (tmp_path / "vault").mkdir(parents=True, exist_ok=True)
    (tmp_path / "recordings").mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(doc))
    return path


class TestCreateMutation:
    def test_create_appends_new_contact(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[])
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "create", "name": "Alice", "display_name": "Alice",
             "email": "alice@x.com"},
        ])
        doc = yaml.safe_load(path.read_text())
        contacts = doc["known-contacts"]
        assert len(contacts) == 1
        assert contacts[0]["name"] == "Alice"
        assert contacts[0]["display-name"] == "Alice"
        assert contacts[0]["email"] == "alice@x.com"

    def test_create_without_email(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[])
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "create", "name": "Bob", "display_name": "Bob"},
        ])
        doc = yaml.safe_load(path.read_text())
        entry = doc["known-contacts"][0]
        assert entry["name"] == "Bob"
        # No email key (or email: None) -- either is acceptable, but no spurious value.
        assert entry.get("email") in (None, "")

    def test_create_missing_name_raises(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[])
        daemon = _fake_daemon(path)
        with pytest.raises(ValueError):
            _apply_contact_mutations(daemon, [
                {"action": "create", "display_name": "Alice"},
            ])

    def test_create_creates_known_contacts_section_if_missing(self, tmp_path):
        """If the YAML has no known-contacts section at all, create one."""
        path = _write_min_config(tmp_path, contacts=None)
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "create", "name": "Alice", "display_name": "Alice"},
        ])
        doc = yaml.safe_load(path.read_text())
        assert len(doc["known-contacts"]) == 1

    def test_create_idempotent_on_existing_name(self, tmp_path):
        """Same-name create is a no-op (retry safety)."""
        path = _write_min_config(tmp_path, contacts=[
            {"name": "Alice", "display-name": "Alice"},
        ])
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "create", "name": "Alice", "display_name": "Alice Different"},
        ])
        doc = yaml.safe_load(path.read_text())
        # Only one Alice; original display-name preserved (no overwrite).
        assert len(doc["known-contacts"]) == 1
        assert doc["known-contacts"][0]["display-name"] == "Alice"


class TestAddAliasMutation:
    def test_add_alias_extends_list(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[
            {"name": "Sean Mooney", "display-name": "Sean Mooney"},
        ])
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "add_alias", "name": "Sean Mooney", "alias": "Sean M."},
        ])
        doc = yaml.safe_load(path.read_text())
        assert doc["known-contacts"][0].get("aliases") == ["Sean M."]

    def test_add_alias_idempotent(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[
            {"name": "Sean Mooney", "display-name": "Sean Mooney",
             "aliases": ["Sean M."]},
        ])
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "add_alias", "name": "Sean Mooney", "alias": "Sean M."},
        ])
        doc = yaml.safe_load(path.read_text())
        assert doc["known-contacts"][0]["aliases"] == ["Sean M."]

    def test_add_alias_target_not_found_raises(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[])
        daemon = _fake_daemon(path)
        with pytest.raises(ValueError):
            _apply_contact_mutations(daemon, [
                {"action": "add_alias", "name": "Ghost", "alias": "Nope"},
            ])


class TestAtomicity:
    def test_unknown_action_raises_disk_unchanged(self, tmp_path):
        path = _write_min_config(tmp_path, contacts=[])
        before = path.read_text()
        daemon = _fake_daemon(path)
        with pytest.raises(ValueError):
            _apply_contact_mutations(daemon, [{"action": "nonexistent"}])
        # Atomic: file unchanged on failure.
        assert path.read_text() == before

    def test_preserves_user_custom_comments(self, tmp_path):
        """ruamel round-trip preserves comments and custom fields."""
        path = tmp_path / "config.yaml"
        (tmp_path / "vault").mkdir()
        (tmp_path / "recordings").mkdir()
        vault_path = (tmp_path / "vault").as_posix()
        rec_path = (tmp_path / "recordings").as_posix()
        path.write_text(f"""# User's custom comment
config-version: 1
vault-path: {vault_path}
recordings-path: {rec_path}
user-name: Tester
orgs:
  test:
    subfolder: Test
    llm-backend: claude
    default: true
detection: {{}}
calendars: {{}}
known-contacts:
- name: Alice
  display-name: Alice
  custom-field: value  # custom field preserved
""")
        daemon = _fake_daemon(path)
        _apply_contact_mutations(daemon, [
            {"action": "create", "name": "Bob", "display_name": "Bob"},
        ])
        text = path.read_text()
        assert "User's custom comment" in text
        assert "custom field preserved" in text  # comment preserved
        assert "custom-field: value" in text  # field preserved
        assert "Bob" in text
