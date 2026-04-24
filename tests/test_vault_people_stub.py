"""Tests for _ensure_people_stub daemon helper (#28 Task 12)."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest


def _fake_daemon_with_org(
    tmp_path: Path, *, org_slug: str = "test", subfolder: str = "Test",
) -> MagicMock:
    """Minimal fake daemon with enough config for _ensure_people_stub."""
    d = MagicMock()
    d.config.vault_path = tmp_path
    # Fake OrgConfig
    org_config = MagicMock()
    org_config.resolve_subfolder = lambda vp: vp / subfolder
    # org_by_slug is a method on DaemonConfig; configure to return the org
    # or None when unknown.
    def _org_by_slug(slug):
        if slug == org_slug:
            return org_config
        return None
    d.config.org_by_slug = _org_by_slug
    return d


def test_creates_stub_using_canonical_template(tmp_path):
    """Calls existing _generate_person_stub from recap.vault."""
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path)
    _ensure_people_stub(daemon, "test", "Alice")
    stub = tmp_path / "Test" / "People" / "Alice.md"
    assert stub.exists()
    # Canonical template produces more than a bare title.
    content = stub.read_text(encoding="utf-8")
    assert len(content) > len("# Alice\n")


def test_idempotent_no_clobber(tmp_path):
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path)
    stub_path = tmp_path / "Test" / "People" / "Alice.md"
    stub_path.parent.mkdir(parents=True)
    stub_path.write_text("# Alice\n\nUser-edited content that must survive.\n",
                         encoding="utf-8")
    _ensure_people_stub(daemon, "test", "Alice")
    assert "User-edited content" in stub_path.read_text(encoding="utf-8")


def test_creates_people_dir_if_missing(tmp_path):
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path)
    # Neither Test/ nor Test/People/ exists.
    _ensure_people_stub(daemon, "test", "Alice")
    assert (tmp_path / "Test" / "People" / "Alice.md").exists()


def test_unknown_org_raises(tmp_path):
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path)
    with pytest.raises(ValueError):
        _ensure_people_stub(daemon, "bogus-org", "Alice")


def test_sanitizes_filename(tmp_path):
    """Names with slashes get safe_note_title treatment (no directory traversal)."""
    from recap.daemon.server import _ensure_people_stub
    daemon = _fake_daemon_with_org(tmp_path)
    _ensure_people_stub(daemon, "test", "A/B")
    # safe_note_title should replace the slash. Exact sanitization depends on
    # the existing safe_note_title in recap.artifacts.
    files = list((tmp_path / "Test" / "People").glob("*.md"))
    assert len(files) == 1
    # The created file's name (basename) must not contain a slash.
    assert "/" not in files[0].name
