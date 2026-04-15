"""Tests for the daemon notifications module (§0.4 journal integration)."""
from __future__ import annotations

import logging
import pathlib
from unittest.mock import MagicMock, patch

import pytest

from recap.daemon.events import EventJournal
from recap.daemon.notifications import notify


@pytest.fixture(autouse=True)
def _stub_plyer(monkeypatch):
    """Stub out plyer.notification so the OS toast never fires in tests.

    The plyer import happens inside ``notify()`` so we patch ``sys.modules``
    to inject a fake ``plyer`` module before the first call.
    """
    import sys
    import types

    fake_plyer = types.ModuleType("plyer")
    fake_plyer.notification = MagicMock()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "plyer", fake_plyer)
    yield fake_plyer


class TestNotifyJournalIntegration:
    def test_notify_appends_to_journal(self, tmp_path: pathlib.Path) -> None:
        journal = EventJournal(tmp_path / "events.jsonl")
        notify(
            "Test Title",
            "Test body",
            journal=journal,
            level="info",
            event="test",
        )
        entries = journal.tail(limit=10)
        assert any(
            e["message"] == "Test body" and e["event"] == "test"
            for e in entries
        )

    def test_notify_payload_includes_title(self, tmp_path: pathlib.Path) -> None:
        journal = EventJournal(tmp_path / "events.jsonl")
        notify("Recap", "Meeting processed", journal=journal)
        entries = journal.tail(limit=10)
        assert len(entries) == 1
        entry = entries[0]
        assert entry["message"] == "Meeting processed"
        assert entry["event"] == "notification"  # default
        assert entry["level"] == "info"  # default
        assert entry["payload"] == {"title": "Recap"}

    def test_notify_without_journal_does_not_raise(self) -> None:
        """Backward-compat: callers without a journal still work."""
        notify("Recap", "No journal")  # should not raise

    def test_notify_with_journal_none_does_not_raise(
        self, tmp_path: pathlib.Path,
    ) -> None:
        notify("Recap", "Explicit None", journal=None)  # should not raise

    def test_notify_swallows_journal_failure(
        self, tmp_path: pathlib.Path, caplog,
    ) -> None:
        """A broken journal must not crash ``notify()`` -- it just logs."""
        bad_journal = MagicMock(spec=EventJournal)
        bad_journal.append.side_effect = RuntimeError("disk full")
        with caplog.at_level(logging.ERROR, logger="recap.notifications"):
            notify("Recap", "Will fail", journal=bad_journal)
        # Logged, but didn't propagate.
        assert any(
            "Failed to journal notification" in rec.message for rec in caplog.records
        )

    def test_notify_custom_level_and_event(self, tmp_path: pathlib.Path) -> None:
        journal = EventJournal(tmp_path / "events.jsonl")
        notify(
            "Recap Error",
            "Pipeline crashed",
            journal=journal,
            level="error",
            event="pipeline_failed",
        )
        entries = journal.tail(limit=10)
        assert len(entries) == 1
        assert entries[0]["level"] == "error"
        assert entries[0]["event"] == "pipeline_failed"
        assert entries[0]["message"] == "Pipeline crashed"


class TestNotifyOsToast:
    def test_notify_still_sends_os_toast(
        self, tmp_path: pathlib.Path, _stub_plyer,
    ) -> None:
        """Journal integration must not break the existing OS-notification path."""
        journal = EventJournal(tmp_path / "events.jsonl")
        notify("Recap", "hello", journal=journal)
        _stub_plyer.notification.notify.assert_called_once()
        kwargs = _stub_plyer.notification.notify.call_args.kwargs
        assert kwargs["title"] == "Recap"
        assert kwargs["message"] == "hello"

    def test_notify_toast_failure_does_not_crash(
        self, tmp_path: pathlib.Path, _stub_plyer,
    ) -> None:
        journal = EventJournal(tmp_path / "events.jsonl")
        _stub_plyer.notification.notify.side_effect = RuntimeError("plyer broken")
        # Must not raise.
        notify("Recap", "hello", journal=journal)
        # Journal still appended despite the toast failure.
        assert len(journal.tail(limit=10)) == 1
