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


class TestIsCallActiveLogging:
    """call_state_check debug lines for every return path.

    Each path must emit a single line with platform, hwnd, result, and a
    reason naming the branch taken. The existing exception-fallback
    behavior (result=true on uia errors) is locked in by the fallback
    test below so future changes cannot silently flip detection semantics.

    Refs #30 (diagnostic instrumentation).
    """

    _LOGGER = "recap.daemon.recorder.call_state"

    def test_logs_no_checker_for_unregistered_platform(self, caplog):
        import logging
        from recap.daemon.recorder.call_state import is_call_active

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert is_call_active(hwnd=1, platform="signal") is True

        lines = [
            r.getMessage() for r in caplog.records
            if "call_state_check" in r.getMessage()
        ]
        assert len(lines) == 1
        line = lines[0]
        assert "platform=signal" in line
        assert "result=true" in line
        assert "reason=no_checker_for_platform" in line

    def test_logs_uia_control_not_found(self, monkeypatch, caplog):
        import logging
        import uiautomation
        from recap.daemon.recorder.call_state import is_call_active

        monkeypatch.setattr(uiautomation, "ControlFromHandle", lambda hwnd: None)

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert is_call_active(hwnd=42, platform="teams") is False

        lines = [
            r.getMessage() for r in caplog.records
            if "call_state_check" in r.getMessage()
        ]
        assert len(lines) == 1
        line = lines[0]
        assert "platform=teams" in line
        assert "hwnd=42" in line
        assert "result=false" in line
        assert "reason=uia_control_not_found" in line

    def test_logs_checker_confirmed_true(self, monkeypatch, caplog):
        import logging
        import uiautomation
        from recap.daemon.recorder.call_state import is_call_active

        leave_btn = FakeControl("ButtonControl", "Leave")
        root = FakeControl(children=[leave_btn])
        monkeypatch.setattr(uiautomation, "ControlFromHandle", lambda hwnd: root)

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert is_call_active(hwnd=7, platform="teams") is True

        lines = [
            r.getMessage() for r in caplog.records
            if "call_state_check" in r.getMessage()
        ]
        assert any(
            "result=true" in l and "reason=checker_confirmed" in l
            for l in lines
        )

    def test_logs_checker_declined(self, monkeypatch, caplog):
        import logging
        import uiautomation
        from recap.daemon.recorder.call_state import is_call_active

        chat_btn = FakeControl("ButtonControl", "Chat")
        root = FakeControl(children=[chat_btn])
        monkeypatch.setattr(uiautomation, "ControlFromHandle", lambda hwnd: root)

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert is_call_active(hwnd=8, platform="teams") is False

        lines = [
            r.getMessage() for r in caplog.records
            if "call_state_check" in r.getMessage()
        ]
        assert any(
            "result=false" in l and "reason=checker_declined" in l
            for l in lines
        )

    def test_logs_uia_exception_fallback_returning_true(self, monkeypatch, caplog):
        """Behavior lock: uia exceptions must still produce result=true.
        Flipping this to False would silently change detection semantics
        for platforms with registered checkers.
        """
        import logging
        import uiautomation
        from recap.daemon.recorder.call_state import is_call_active

        def boom(_):
            raise RuntimeError("uia blew up")

        monkeypatch.setattr(uiautomation, "ControlFromHandle", boom)

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert is_call_active(hwnd=9, platform="teams") is True

        lines = [
            r.getMessage() for r in caplog.records
            if "call_state_check" in r.getMessage()
        ]
        assert any(
            "result=true" in l and "reason=uia_exception_fallback" in l
            for l in lines
        )


class TestTeamsCallStateWalkLogging:
    """teams_call_state_walk logging of button names observed during the
    UIA walk when no Leave/Hang up/End call button is found. Refs #30 --
    these are the actual accessible names Teams exposes that we are
    failing to match, and are the evidence needed to decide whether the
    fix is a button-name expansion, a traversal change, or both.
    """

    _LOGGER = "recap.daemon.recorder.call_state"

    def test_logs_button_names_seen_when_no_call_button(self, caplog):
        import logging
        from recap.daemon.recorder.call_state import _is_teams_call_active

        chat = FakeControl("ButtonControl", "Chat")
        activity = FakeControl("ButtonControl", "Activity")
        pane = FakeControl("PaneControl", "side-pane")
        root = FakeControl(children=[chat, pane, activity])

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert _is_teams_call_active(root) is False

        walk_lines = [
            r.getMessage() for r in caplog.records
            if "teams_call_state_walk" in r.getMessage()
        ]
        assert len(walk_lines) == 1
        line = walk_lines[0]
        assert "buttons_seen=" in line
        assert "'Chat'" in line
        assert "'Activity'" in line

    def test_no_walk_log_when_leave_button_found(self, caplog):
        """Positive path does not emit a walk log -- the diagnostic only
        fires when a filter happens, to keep noise low in the healthy case.
        """
        import logging
        from recap.daemon.recorder.call_state import _is_teams_call_active

        leave = FakeControl("ButtonControl", "Leave")
        root = FakeControl(children=[leave])

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert _is_teams_call_active(root) is True

        walk_lines = [
            r.getMessage() for r in caplog.records
            if "teams_call_state_walk" in r.getMessage()
        ]
        assert walk_lines == []

    def test_buttons_seen_skips_empty_names(self, caplog):
        """Icon-only buttons with empty Name must not crowd out useful labels.
        If 20 empty buttons get visited before any named one, the log would
        fill up with blanks and obscure the real evidence.
        """
        import logging
        from recap.daemon.recorder.call_state import _is_teams_call_active

        empty_buttons = [FakeControl("ButtonControl", "") for _ in range(10)]
        whitespace_button = FakeControl("ButtonControl", "   ")
        real_button = FakeControl("ButtonControl", "Activity")
        root = FakeControl(children=[*empty_buttons, whitespace_button, real_button])

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert _is_teams_call_active(root) is False

        walk_lines = [
            r.getMessage() for r in caplog.records
            if "teams_call_state_walk" in r.getMessage()
        ]
        assert len(walk_lines) == 1
        line = walk_lines[0]
        # Non-empty name must appear.
        assert "'Activity'" in line
        # No empty or whitespace-only entries in the list.
        assert "''" not in line
        assert "'   '" not in line

    def test_buttons_seen_list_is_capped(self, caplog):
        """Cap the recorded list to avoid enormous log lines on dense
        UI trees. Implementation caps at 20 entries -- anything more is
        noise for a diagnostic."""
        import logging
        from recap.daemon.recorder.call_state import _is_teams_call_active

        # 50 non-matching buttons; collector should cap at 20
        buttons = [FakeControl("ButtonControl", f"btn-{i}") for i in range(50)]
        root = FakeControl(children=buttons)

        with caplog.at_level(logging.DEBUG, logger=self._LOGGER):
            assert _is_teams_call_active(root) is False

        walk_lines = [
            r.getMessage() for r in caplog.records
            if "teams_call_state_walk" in r.getMessage()
        ]
        assert len(walk_lines) == 1
        # Parse the buttons_seen list length from the formatted line.
        # Line format: "teams_call_state_walk buttons_seen=['btn-0', ...]"
        import re as _re
        match = _re.search(r"buttons_seen=\[([^\]]*)\]", walk_lines[0])
        assert match is not None
        items = [x.strip() for x in match.group(1).split(",") if x.strip()]
        assert len(items) <= 20
