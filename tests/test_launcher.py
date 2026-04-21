"""Tests for the launcher watchdog (``recap.launcher``).

The launcher supervises the daemon as a child process. It loops on
``EXIT_RESTART_REQUESTED`` (42), stops on ``EXIT_STOP`` (0), and bails
loudly on any other exit code. The subprocess itself is mocked here
because spawning real daemons from a unit test is overkill; the
launch contract is narrow enough (argv + env + exit code) that
subprocess mocking covers everything important.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

from recap.daemon.exit_codes import EXIT_RESTART_REQUESTED, EXIT_STOP
from recap import launcher


def _fake_proc(returncode: int) -> MagicMock:
    proc = MagicMock()
    proc.wait.return_value = returncode
    proc.returncode = returncode
    return proc


class TestLauncherExitCodeLoop:
    def test_single_clean_exit_returns_zero(self, tmp_path, monkeypatch):
        """``EXIT_STOP`` exits the launcher with 0 and does not respawn."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        with patch.object(launcher, "_spawn_daemon") as spawn:
            spawn.return_value = _fake_proc(EXIT_STOP)
            code = launcher.run(extra_args=["--config", "dummy.yaml"])
        assert code == EXIT_STOP
        assert spawn.call_count == 1

    def test_restart_code_respawns_then_stops(self, tmp_path, monkeypatch):
        """First child exits 42 (respawn). Second child exits 0 (stop)."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        procs = [_fake_proc(EXIT_RESTART_REQUESTED), _fake_proc(EXIT_STOP)]
        with patch.object(launcher, "_spawn_daemon", side_effect=procs) as spawn:
            code = launcher.run(extra_args=[])
        assert code == EXIT_STOP
        assert spawn.call_count == 2

    def test_fatal_nonzero_bails_without_respawn(self, tmp_path, monkeypatch):
        """Anything other than 0 or 42 = loud exit, no respawn loop."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        with patch.object(launcher, "_spawn_daemon") as spawn:
            spawn.return_value = _fake_proc(1)
            code = launcher.run(extra_args=[])
        assert code == 1
        assert spawn.call_count == 1

    def test_respawn_loop_cap_prevents_crashloop(self, tmp_path, monkeypatch):
        """A daemon stuck returning 42 immediately must not spin forever.

        The cap (kept low for tests) guards against the failure mode
        where a bug triggers ``restart_requested=True`` on every boot
        and the daemon never lives long enough to reset the fast-restart
        counter. Without the cap, the wrapper would peg a CPU spawning
        Python processes."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        monkeypatch.setattr(launcher, "_MAX_RESTARTS", 3)
        with patch.object(launcher, "_spawn_daemon") as spawn:
            spawn.return_value = _fake_proc(EXIT_RESTART_REQUESTED)
            code = launcher.run(extra_args=[])
        # 3 tolerated fast restarts = 1 initial + 3 respawns = 4 spawns,
        # then give up on the 5th (would-be) attempt.
        assert spawn.call_count == 4
        assert code != EXIT_STOP

    def test_healthy_run_resets_restart_counter(
        self, tmp_path, monkeypatch,
    ):
        """A restart after a healthy-length run must NOT count toward
        the crash-loop cap.

        Real-world: user restarts the daemon every time they tweak
        config. Each run is several minutes long, so the launcher
        should tolerate unlimited user-initiated restarts over its
        lifetime. Only *fast* consecutive restarts (< ``_HEALTHY_RUN_SECONDS``)
        signal a crash loop."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        monkeypatch.setattr(launcher, "_MAX_RESTARTS", 2)

        # Alternate: healthy run, fast restart, healthy run, fast restart,
        # ... then finally a clean stop. Without the reset, the second
        # fast restart would trip the cap (cap=2). With the reset, each
        # healthy run wipes the counter so the loop keeps going.
        procs = [
            _fake_proc(EXIT_RESTART_REQUESTED),   # run 1: healthy
            _fake_proc(EXIT_RESTART_REQUESTED),   # run 2: fast
            _fake_proc(EXIT_RESTART_REQUESTED),   # run 3: healthy (resets)
            _fake_proc(EXIT_RESTART_REQUESTED),   # run 4: fast
            _fake_proc(EXIT_RESTART_REQUESTED),   # run 5: healthy (resets)
            _fake_proc(EXIT_STOP),                # run 6: clean exit
        ]
        # time.monotonic() is called twice per iteration (spawn_time + exit).
        # Advance by 60s for "healthy" runs and 1s for "fast" restarts.
        timeline = iter([
            0.0, 60.0,      # run 1 healthy
            60.0, 61.0,     # run 2 fast
            61.0, 121.0,    # run 3 healthy
            121.0, 122.0,   # run 4 fast
            122.0, 182.0,   # run 5 healthy
            182.0, 183.0,   # run 6 (stop -- duration irrelevant)
        ])
        monkeypatch.setattr(launcher.time, "monotonic", lambda: next(timeline))

        with patch.object(launcher, "_spawn_daemon", side_effect=procs) as spawn:
            code = launcher.run(extra_args=[])
        assert code == EXIT_STOP
        assert spawn.call_count == 6


class TestLauncherEnvAndArgs:
    def test_spawn_sets_recap_managed_env(self, tmp_path, monkeypatch):
        """Child process env must include ``RECAP_MANAGED=1`` so the
        daemon's ``/api/status`` advertises ``can_restart: true``."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        captured: dict = {}

        def fake_popen(argv, env, stdout, stderr):
            captured["argv"] = argv
            captured["env"] = env
            return _fake_proc(EXIT_STOP)

        with patch.object(launcher.subprocess, "Popen", side_effect=fake_popen):
            launcher.run(extra_args=["--config", "custom.yaml"])

        assert captured["env"].get("RECAP_MANAGED") == "1"
        # Sanity: daemon module in argv so we're launching the right thing.
        joined = " ".join(captured["argv"])
        assert "recap.daemon" in joined

    def test_extra_args_pass_through_to_daemon(self, tmp_path, monkeypatch):
        """Args after the module name (e.g. ``--config path.yaml``) must
        reach the daemon child unmodified -- the launcher is a
        pass-through supervisor, not a config parser."""
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(tmp_path / "launcher.log"))
        captured: dict = {}

        def fake_popen(argv, env, stdout, stderr):
            captured["argv"] = argv
            return _fake_proc(EXIT_STOP)

        with patch.object(launcher.subprocess, "Popen", side_effect=fake_popen):
            launcher.run(extra_args=["--config", "custom.yaml", "--verbose"])

        assert "--config" in captured["argv"]
        assert "custom.yaml" in captured["argv"]
        assert "--verbose" in captured["argv"]


class TestLauncherLogging:
    def test_writes_restart_markers_to_launcher_log(
        self, tmp_path, monkeypatch, caplog,
    ):
        """Each child run must leave a start+exit marker in the launcher
        log so post-mortem debugging can see 'child 1 exited 42, child
        2 exited 0' without chasing logs inside the daemon itself."""
        log_path = tmp_path / "launcher.log"
        monkeypatch.setenv("RECAP_LAUNCHER_LOG", str(log_path))
        procs = [_fake_proc(EXIT_RESTART_REQUESTED), _fake_proc(EXIT_STOP)]
        with patch.object(launcher, "_spawn_daemon", side_effect=procs):
            with caplog.at_level(logging.INFO, logger="recap.launcher"):
                launcher.run(extra_args=[])

        messages = [r.getMessage() for r in caplog.records]
        # Each child has a start marker and an exit marker.
        starts = [m for m in messages if "daemon child starting" in m.lower()]
        exits = [m for m in messages if "daemon child exited" in m.lower()]
        assert len(starts) == 2
        assert len(exits) == 2
        # File handler appended too.
        assert log_path.exists()
        log_text = log_path.read_text(encoding="utf-8")
        assert "daemon child starting" in log_text.lower()
        assert "daemon child exited" in log_text.lower()
