"""Tests for the daemon event journal (design §0.4)."""
from __future__ import annotations

import json
import pathlib
import threading

from recap.daemon.events import EventJournal


def _make_journal(tmp_path: pathlib.Path, **kwargs) -> EventJournal:
    return EventJournal(tmp_path / "events.jsonl", **kwargs)


class TestEventJournalAppend:
    def test_append_writes_one_line_per_entry(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("info", "startup", "Daemon started")
        j.append("warning", "silence_warning", "No audio for 5 minutes")
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 2
        e0 = json.loads(lines[0])
        assert e0["level"] == "info"
        assert e0["event"] == "startup"
        assert e0["message"] == "Daemon started"
        assert "ts" in e0
        assert "." in e0["ts"]
        assert "payload" not in e0  # omitted when None

    def test_append_includes_payload_when_provided(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("error", "pipeline_failed", "boom", payload={"stage": "analyze"})
        line = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()[0]
        e = json.loads(line)
        assert e["payload"] == {"stage": "analyze"}

    def test_append_is_thread_safe(self, tmp_path):
        j = _make_journal(tmp_path)
        def writer(n):
            for i in range(50):
                j.append("info", "t", f"w{n}-{i}")
        threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
        for t in threads: t.start()
        for t in threads: t.join()
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 200
        # Each line must be valid JSON (no interleaving corruption)
        for line in lines:
            json.loads(line)


class TestEventJournalTail:
    def test_tail_returns_last_n_in_order(self, tmp_path):
        j = _make_journal(tmp_path)
        for i in range(5):
            j.append("info", "e", f"m{i}")
        entries = j.tail(limit=3)
        assert len(entries) == 3
        assert [e["message"] for e in entries] == ["m2", "m3", "m4"]

    def test_tail_filters_by_level(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("info", "a", "m-info")
        j.append("error", "b", "m-error-1")
        j.append("warning", "c", "m-warn")
        j.append("error", "d", "m-error-2")
        errors = j.tail(level="error", limit=10)
        assert [e["message"] for e in errors] == ["m-error-1", "m-error-2"]

    def test_tail_empty_file_returns_empty_list(self, tmp_path):
        j = _make_journal(tmp_path)
        assert j.tail(limit=10) == []

    def test_tail_ignores_corrupt_lines(self, tmp_path):
        j = _make_journal(tmp_path)
        j.append("info", "a", "ok")
        (tmp_path / "events.jsonl").open("a", encoding="utf-8").write("not json\n")
        j.append("info", "b", "ok-2")
        entries = j.tail(limit=10)
        assert [e["message"] for e in entries] == ["ok", "ok-2"]


class TestEventJournalRotation:
    def test_rotates_at_max_bytes(self, tmp_path):
        # Tiny threshold to trigger rotation reliably
        j = _make_journal(tmp_path, max_bytes=256)
        for i in range(20):
            j.append("info", "e", f"message-{i:03d}-{'x' * 20}")
        assert (tmp_path / "events.jsonl").exists()
        assert (tmp_path / "events.jsonl.1").exists()
        # Current file is below threshold after rotation
        assert (tmp_path / "events.jsonl").stat().st_size <= 256 * 2

    def test_rotation_keeps_one_backup(self, tmp_path):
        j = _make_journal(tmp_path, max_bytes=128)
        for i in range(40):
            j.append("info", "e", f"m{i}" + "x" * 30)
        # Only events.jsonl and events.jsonl.1 — no .2, .3
        assert (tmp_path / "events.jsonl").exists()
        assert (tmp_path / "events.jsonl.1").exists()
        assert not (tmp_path / "events.jsonl.2").exists()

    def test_prune_old_backups_deletes_stale(self, tmp_path):
        import os, time
        j = _make_journal(tmp_path, max_bytes=64)
        for i in range(30):
            j.append("info", "e", f"m{i}" + "x" * 10)
        backup = tmp_path / "events.jsonl.1"
        assert backup.exists()
        # Artificially age the backup by 31 days
        old = time.time() - 31 * 86400
        os.utime(backup, (old, old))
        j.prune_old_backups(max_age_days=30)
        assert not backup.exists()


class TestJournalSubscribers:
    """Task 6: pub-sub shim so the HTTP layer can broadcast new entries."""

    def test_subscribe_receives_appended_entries(self, tmp_path):
        j = _make_journal(tmp_path)
        received: list[dict] = []
        unsubscribe = j.subscribe(received.append)

        j.append("info", "e1", "m1")
        j.append("info", "e2", "m2")

        assert [e["event"] for e in received] == ["e1", "e2"]
        assert [e["message"] for e in received] == ["m1", "m2"]

        unsubscribe()
        j.append("info", "e3", "m3")

        # Unsubscribed callback sees no further entries.
        assert [e["event"] for e in received] == ["e1", "e2"]

    def test_subscribe_returns_unsubscribe_callable(self, tmp_path):
        j = _make_journal(tmp_path)
        unsub = j.subscribe(lambda _e: None)
        assert callable(unsub)
        # Double-unsubscribe is a no-op.
        unsub()
        unsub()

    def test_multiple_subscribers_each_receive_entries(self, tmp_path):
        j = _make_journal(tmp_path)
        a: list[dict] = []
        b: list[dict] = []
        j.subscribe(a.append)
        j.subscribe(b.append)

        j.append("warning", "silence", "no audio")

        assert len(a) == 1
        assert len(b) == 1
        assert a[0]["event"] == "silence"
        assert b[0]["event"] == "silence"

    def test_subscriber_receives_payload_when_present(self, tmp_path):
        j = _make_journal(tmp_path)
        received: list[dict] = []
        j.subscribe(received.append)

        j.append("error", "pipeline_failed", "boom", payload={"stage": "analyze"})

        assert received[0]["payload"] == {"stage": "analyze"}
        assert received[0]["level"] == "error"
        assert "ts" in received[0]

    def test_subscriber_exception_does_not_block_journal(self, tmp_path, caplog):
        """A misbehaving subscriber must not prevent the append from persisting."""
        j = _make_journal(tmp_path)

        def _boom(_entry: dict) -> None:
            raise RuntimeError("subscriber broken")

        j.subscribe(_boom)
        # Follow-on good subscriber must still fire.
        good: list[dict] = []
        j.subscribe(good.append)

        with caplog.at_level("ERROR"):
            j.append("info", "ok", "still writes")

        # File was written.
        lines = (tmp_path / "events.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(lines) == 1
        # Good subscriber still ran after the bad one raised.
        assert len(good) == 1
        # Exception was logged, not propagated.
        assert any(
            "Journal subscriber raised" in r.getMessage()
            for r in caplog.records
        )

    def test_subscriber_fires_from_append_thread(self, tmp_path):
        """Subscribers run on whatever thread invoked append()."""
        import threading as _t
        j = _make_journal(tmp_path)
        thread_ids: list[int] = []
        j.subscribe(lambda _e: thread_ids.append(_t.get_ident()))

        other_thread_ident: dict[str, int] = {}

        def _writer() -> None:
            other_thread_ident["id"] = _t.get_ident()
            j.append("info", "from_thread", "hi")

        t = _t.Thread(target=_writer)
        t.start()
        t.join()

        assert thread_ids == [other_thread_ident["id"]]
        assert thread_ids[0] != _t.get_ident()

    def test_unsubscribe_during_iteration_is_safe(self, tmp_path):
        """A subscriber that unsubscribes itself shouldn't corrupt fan-out."""
        j = _make_journal(tmp_path)
        seen_a: list[dict] = []
        seen_b: list[dict] = []

        # Register callback A, grab an unsubscribe handle.
        def _a(entry: dict) -> None:
            seen_a.append(entry)
            unsub_a()  # self-unsubscribe mid-fan-out

        unsub_a = j.subscribe(_a)
        j.subscribe(seen_b.append)

        j.append("info", "first", "m1")
        j.append("info", "second", "m2")

        # A fired once, then unsubscribed.
        assert [e["event"] for e in seen_a] == ["first"]
        # B keeps receiving.
        assert [e["event"] for e in seen_b] == ["first", "second"]

    def test_append_is_thread_safe_with_subscribers(self, tmp_path):
        """Concurrent appends must deliver each entry to subscribers exactly once."""
        j = _make_journal(tmp_path)
        lock = threading.Lock()
        received: list[dict] = []

        def _cb(entry: dict) -> None:
            with lock:
                received.append(entry)

        j.subscribe(_cb)

        def _writer(n: int) -> None:
            for i in range(25):
                j.append("info", f"t{n}", f"w{n}-{i}")

        threads = [threading.Thread(target=_writer, args=(n,)) for n in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Subscriber got called once per append across all writers.
        assert len(received) == 100
