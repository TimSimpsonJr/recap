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

    def test_checkers_registered_for_teams_and_zoom(self):
        # Task 11 populates checkers for teams + zoom.
        # Signal intentionally remains regex-only (§3.6 per-platform policy).
        assert has_call_state_checker("teams") is True
        assert has_call_state_checker("zoom") is True
        assert has_call_state_checker("signal") is False

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


class FakeControl:
    def __init__(self, ControlTypeName="", Name="", children=None):
        self.ControlTypeName = ControlTypeName
        self.Name = Name
        self._children = children or []

    def GetChildren(self):
        return self._children


def test_is_call_active_returns_true_when_leave_button_present():
    from recap.daemon.recorder.call_state import _is_teams_call_active
    leave_btn = FakeControl("ButtonControl", "Leave")
    root = FakeControl(children=[leave_btn])
    assert _is_teams_call_active(root) is True


def test_is_call_active_returns_false_when_no_call_controls():
    from recap.daemon.recorder.call_state import _is_teams_call_active
    chat_btn = FakeControl("ButtonControl", "Chat")
    root = FakeControl(children=[chat_btn])
    assert _is_teams_call_active(root) is False


def test_is_call_active_returns_true_for_unregistered_platform():
    from recap.daemon.recorder.call_state import is_call_active
    assert is_call_active(hwnd=1, platform="signal") is True


def test_is_call_active_returns_true_on_uia_exception(monkeypatch):
    import uiautomation
    from recap.daemon.recorder.call_state import is_call_active
    def raise_it(_): raise RuntimeError("uia broken")
    monkeypatch.setattr(uiautomation, "ControlFromHandle", raise_it)
    assert is_call_active(hwnd=1, platform="teams") is True


def test_is_call_active_returns_false_when_control_is_none(monkeypatch):
    """If UIA returns None for the hwnd, is_call_active must NOT pretend
    the regex match is a confirmed call. Returning True here would reopen
    the false-positive class Phase 7's UIA gate was introduced to close.

    Distinct from test_is_call_active_returns_true_on_uia_exception, which
    covers transient UIA runtime errors.
    """
    import uiautomation
    from recap.daemon.recorder.call_state import is_call_active

    monkeypatch.setattr(uiautomation, "ControlFromHandle", lambda hwnd: None)
    assert is_call_active(hwnd=1, platform="teams") is False
