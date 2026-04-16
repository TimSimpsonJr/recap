# Phase 7 — ML Stack Refresh

**Status:** proposed (unbranched)
**Parent:** `docs/plans/2026-04-14-fix-everything-design.md` (post Final Integration Pass)
**Discovered during:** 2026-04-16 manual setup walkthrough on real hardware

---

## Why this phase exists

On 2026-04-16 the `obsidian-pivot` branch had:
- 573 pytest tests passing
- 71.43% coverage over `recap/`
- All 8 Review Blockers from the parent design verified
- A published "Final Integration Pass" handoff claiming all automated gates green

When the daemon was actually started against a real vault + the `--extra ml` dependency set, startup cascaded through five distinct failures. None of them were caught by the test suite. The reason is structural: the tests mock at the library boundary (`recap.pipeline.transcribe.transcribe`, `recap.analyze.subprocess.run`, `recap.daemon.streaming.transcriber`, etc.) rather than exercising the real libraries. A library API can change underneath the mocks and the suite stays green.

This phase makes the ML stack actually work end-to-end AND fixes the test-coverage lie that hid the drift.

## Scope

### A. Library drift fixes

1. **`parakeet-stream 0.6.0` API rewrite.** Our code calls `parakeet_stream.load_model(model_name, device=...)` in `recap/daemon/streaming/transcriber.py::_load_model`. The 0.6 surface is class-based: `Parakeet`, `StreamingTranscriber`, `LiveTranscriber`, `ParakeetClient`. Rewrite `_load_model` against the current API. Evaluate whether we should drop the `parakeet-stream` wrapper and call NeMo directly (fewer layers, fewer places for drift).

2. **`pyflac 3.0.0` API change.** `recap/daemon/recorder/audio.py::start` passes `channels=self._channels` to `runtime_pyflac.StreamEncoder(...)`. pyFLAC 3.0 dropped that kwarg. Update the call site to the 3.0 surface (encoder likely infers channel count from the first frame or accepts a different parameter name).

3. **`pyarrow ≥ 21` removed `PyExtensionType`.** NeMo 2.5.0 / lhotse references the deprecated symbol. Two resolutions:
   - Pin `pyarrow < 21` (risk: other deps may require newer).
   - Upgrade NeMo past the version using the dead symbol (risk: further drift).
   Pick the one with the smaller blast radius after checking `uv tree`.

### B. Code bugs surfaced by the startup log

4. **Meeting detection fires on idle apps.** Observed on 2026-04-16: with Teams Desktop running but no call active, the detector triggered `auto-record teams meeting (org=disbursecloud)` within 500 ms of daemon startup. The window-title match is too eager. Detection needs to distinguish a Teams call window from the Teams home/chat window.

5. **Signal popup tkinter threading.** Signal Desktop being open triggered the signal detector's prompt popup on a loop. The tkinter popup crashed with `Tcl_AsyncDelete: async handler deleted by the wrong thread` / `main thread is not in main loop`. The popup must run on the main thread OR be replaced with a Qt/plyer notification that is thread-safe. Also: the "signal" detector should only match Signal *calls*, not every Signal window.

6. **Detection default behavior.** Current config defaults are `auto-record` for Teams and Zoom. This is the correct production default but makes the daemon hostile to run on any machine where those apps are open for non-meeting reasons. Consider a developer mode (env var or config flag) that downgrades all detection to `prompt` or `disabled`.

### C. Test-coverage honesty

7. **Add real-integration smoke tests.** At least one pytest per library boundary that imports the actual library and exercises the call shape. Gated with `@pytest.mark.skipif(no_gpu, reason=...)` so CI without a GPU still runs. Goal: when `parakeet-stream`, `pyflac`, or `pyarrow` bump major versions, `uv run pytest -m integration` fails immediately.

8. **End-to-end smoke test.** One test that runs the full pipeline on a short silent FLAC through `run_pipeline` with real transcribe + diarize + analyze (analyze stubbed to a local ollama model for speed). Catches the entire class of drift the current mocks hide.

9. **Startup smoke test for the daemon.** Spawn the daemon in a subprocess, wait for `auth-token` file, hit `/api/status`, kill the daemon. Would have caught the `parakeet_stream.load_model` error at CI time, not on a user's machine.

## Explicitly out of scope

- Packaging / installer work (that's Phase 9, already designed).
- Production-grade detection heuristics (a proper "is this window actually in a call" detector is a separate problem).
- Migrating away from `tkinter` for the popup UI (flag as follow-up if the threading fix is non-trivial).
- Performance optimization of streaming transcription.

## Order of attack

Brainstorm before coding. The right sequence probably is:

1. Get the daemon to boot cleanly without the ML subsystems loading (toggle config, skip streaming init) so 3/4/5 scenarios can run today. Commit as a scoped fix.
2. Write the honesty tests (B-7, B-8, B-9) FIRST — as failing tests. They document what Phase 7 is delivering.
3. Fix the three library bugs, letting the tests go green one at a time.
4. Fix the detection + popup bugs.
5. Run all 5 manual scenarios on real hardware.
6. Merge.

## Success criteria

- `uv run pytest` still 70%+ coverage, still green.
- `uv run pytest -m integration` (new marker) runs real-library tests on a GPU box and fails when any library boundary drifts.
- Daemon starts with no `--extra ml` subsystem crashes.
- All 5 manual scenarios in `docs/handoffs/2026-04-15-final-integration-pass.md` pass on real hardware.
- Detection does NOT fire when Teams/Zoom/Signal apps are merely running (only when a meeting/call window is actually active).

## Known unknowns to resolve in brainstorming

- Is `parakeet-stream` the right wrapper, or should we call NeMo directly and delete the dependency? Trade-off: `parakeet-stream` wraps model loading + chunking niceties; NeMo-direct gives us fewer layers but more boilerplate.
- What does the pyflac 3.0 `StreamEncoder` surface actually look like? Need to read the 3.0 docs before writing the fix.
- `pyarrow<21` vs. upgrade NeMo — which has smaller blast radius in `uv tree`?
- Is there a detection library (e.g. accessibility APIs) that can reliably identify "in a call" state, or are we stuck with window-title heuristics?
