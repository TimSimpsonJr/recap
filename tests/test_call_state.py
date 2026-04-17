"""Tests for recap.daemon.recorder.call_state.

Task 10 extracts UIA participant extraction into its own module. No
direct unit tests for ``extract_teams_participants`` existed prior to
this refactor (it's exercised via ``test_enrichment`` with UIA mocked
out), so this file starts with smoke tests for the public surface and
an in-process test for the generic ``_walk_depth_limited`` helper.
Task 11 will add call-state checker tests here.
"""
from __future__ import annotations

from recap.daemon.recorder import call_state
from recap.daemon.recorder.call_state import (
    _walk_depth_limited,
    extract_teams_participants,
    has_call_state_checker,
    is_call_active,
)


class _FakeControl:
    """Minimal stand-in for a uiautomation control node."""

    def __init__(self, name: str, children: list["_FakeControl"] | None = None):
        self.name = name
        self._children = children or []

    def GetChildren(self) -> list["_FakeControl"]:
        return list(self._children)


class TestPublicSurface:
    def test_extract_teams_participants_is_exported(self):
        assert callable(extract_teams_participants)

    def test_is_call_active_is_exported(self):
        assert callable(is_call_active)

    def test_has_call_state_checker_is_exported(self):
        assert callable(has_call_state_checker)

    def test_no_checkers_registered_by_default(self):
        # Task 10 ships with an empty dict; Task 11 populates it.
        assert has_call_state_checker("teams") is False
        assert has_call_state_checker("zoom") is False

    def test_is_call_active_returns_true_when_no_checker(self):
        # Regex-trust fallback — no checker registered means "assume active".
        assert is_call_active(hwnd=12345, platform="teams") is True


class TestWalkDepthLimited:
    def test_returns_first_match(self):
        target = _FakeControl("target")
        root = _FakeControl("root", [_FakeControl("a"), target, _FakeControl("b")])
        found = _walk_depth_limited(root, lambda c: c.name == "target")
        assert found is target

    def test_returns_none_when_no_match(self):
        root = _FakeControl("root", [_FakeControl("a"), _FakeControl("b")])
        found = _walk_depth_limited(root, lambda c: c.name == "missing")
        assert found is None

    def test_respects_max_depth(self):
        # Build a chain deeper than max_depth.
        leaf = _FakeControl("leaf")
        node = leaf
        for _ in range(20):
            node = _FakeControl("mid", [node])
        found = _walk_depth_limited(node, lambda c: c.name == "leaf", max_depth=5)
        assert found is None

    def test_exception_in_matcher_is_swallowed(self):
        def boom(_c):
            raise RuntimeError("matcher failed")

        root = _FakeControl("root")
        # Should log at debug and return None, not raise.
        assert _walk_depth_limited(root, boom) is None


class TestModuleImportCompatibility:
    def test_enrichment_reexports_extract_teams_participants(self):
        # Preserve the legacy import path for callers/patches.
        from recap.daemon.recorder.enrichment import (
            extract_teams_participants as reexported,
        )

        assert reexported is call_state.extract_teams_participants
