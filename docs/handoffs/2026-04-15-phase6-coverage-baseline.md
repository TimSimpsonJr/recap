# Phase 6 coverage baseline

**Date:** 2026-04-15
**Branch:** obsidian-pivot
**Commit at measurement:** 7b1c49c5165bae5e4b7d6450fe11ae30048f9ef2
**Tool:** pytest-cov 7.1.0 (coverage 7.13.5)
**Suite:** 552 passed, 3 skipped in 37.7s

**Total coverage over `recap/`:** 71% (4247 statements, 1217 missed)

## Per-module breakdown (lowest 12 by coverage)

| Module                                     | Stmts | Miss | Cover |
|--------------------------------------------|------:|-----:|------:|
| `recap/__main__.py`                        |     3 |    3 |    0% |
| `recap/cli.py`                             |    44 |   44 |    0% |
| `recap/daemon/__main__.py`                 |   189 |  189 |    0% |
| `recap/daemon/tray.py`                     |    66 |   66 |    0% |
| `recap/daemon/recorder/signal_popup.py`    |    59 |   46 |   22% |
| `recap/daemon/recorder/recorder.py`        |   211 |  130 |   38% |
| `recap/daemon/recorder/enrichment.py`      |    60 |   36 |   40% |
| `recap/daemon/recorder/audio.py`           |   190 |  109 |   43% |
| `recap/pipeline/transcribe.py`             |    35 |   14 |   60% |
| `recap/pipeline/diarize.py`                |    42 |   16 |   62% |
| `recap/daemon/calendar/scheduler.py`       |   165 |   52 |   68% |
| `recap/daemon/server.py`                   |   541 |  171 |   68% |

## Per-module breakdown (the rest, for context)

| Module                                         | Stmts | Miss | Cover |
|------------------------------------------------|------:|-----:|------:|
| `recap/daemon/streaming/diarizer.py`           |    69 |   21 |   70% |
| `recap/daemon/recorder/detection.py`           |    33 |   10 |   70% |
| `recap/daemon/credentials.py`                  |    38 |   11 |   71% |
| `recap/daemon/streaming/transcriber.py`        |    60 |   17 |   72% |
| `recap/errors.py`                              |    66 |   16 |   76% |
| `recap/daemon/calendar/google.py`              |    52 |   11 |   79% |
| `recap/daemon/recorder/detector.py`            |   182 |   37 |   80% |
| `recap/daemon/api_config.py`                   |   286 |   56 |   80% |
| `recap/daemon/calendar/zoho.py`                |    53 |   10 |   81% |
| `recap/daemon/logging_setup.py`                |    32 |    5 |   84% |
| `recap/daemon/startup.py`                      |    59 |    8 |   86% |
| `recap/daemon/service.py`                      |   153 |   21 |   86% |
| `recap/daemon/calendar/sync.py`                |   171 |   22 |   87% |
| `recap/analyze.py`                             |    66 |    8 |   88% |
| `recap/daemon/recorder/recovery.py`            |    24 |    3 |   88% |
| `recap/daemon/events.py`                       |    92 |   10 |   89% |
| `recap/pipeline/__init__.py`                   |   237 |   26 |   89% |
| `recap/daemon/calendar/index.py`               |    94 |    9 |   90% |
| `recap/daemon/recorder/state_machine.py`       |    64 |    6 |   91% |
| `recap/daemon/calendar/oauth.py`               |    74 |    6 |   92% |
| `recap/pipeline/audio_convert.py`              |    24 |    2 |   92% |
| `recap/vault.py`                               |   263 |   17 |   94% |
| `recap/artifacts.py`                           |    81 |    4 |   95% |
| `recap/models.py`                              |   110 |    5 |   95% |
| `recap/daemon/config.py`                       |   131 |    0 |  100% |
| `recap/daemon/auth.py`                         |    13 |    0 |  100% |
| `recap/daemon/notifications.py`                |    15 |    0 |  100% |
| `recap/daemon/pairing.py`                      |    62 |    0 |  100% |
| `recap/daemon/recorder/silence.py`             |    24 |    0 |  100% |
| `recap/daemon/runtime_config.py`               |     7 |    0 |  100% |
| `recap/daemon/signal_metadata.py`              |     7 |    0 |  100% |

## Notes

- **Phase 6 target: 70%. Gap: +1 pp (already over the line).**
- Modules Tasks 2-5 are likely to raise:
  - Task 2 (pipeline + vault + artifacts): `recap/pipeline/__init__.py` (89 -> higher), `recap/vault.py` (94 -> higher), `recap/artifacts.py` (95 -> higher). Tiny deltas on small miss counts.
  - Task 3 (pipeline analyze routing): `recap/analyze.py` (88) and `recap/pipeline/__init__.py` (89). Targets the 26 missed lines around analyze branching (120-213, 423-433, 502-503).
  - Task 5 (server auth surface): `recap/daemon/server.py` (68 -> higher). 171 missed lines, so the biggest mover in absolute statements. Likely the single largest contribution to total %.
- Modules where coverage may drop after Tasks 6-7 deletions: any module whose only exercise comes from a test being deleted. Worth auditing per-deletion; if a 100%-covered module (e.g. `pairing.py`, `notifications.py`, `signal_metadata.py`) loses its only test, it falls to 0% and drags total.
- Never-imported entry points (`__main__.py`, `cli.py`, `tray.py`, `daemon/__main__.py`, `signal_popup.py`) account for 317 of the 1217 missed statements (~26%). These are hard to cover without launching the process; if they were excluded via `.coveragerc` the baseline would jump to ~81%. Not recommending that now — Task 8 should decide whether to exclude or accept the drag.

## Assessment

**70% gate: achievable, with low risk.** Baseline is already 71%, so the phase starts 1 pp above the floor. Tasks 2-5 should push numerator up; Tasks 6-7 could shave the denominator (or the numerator, if a deletion removes coverage of otherwise-covered code). The real risk is a Task 6-7 deletion that kills coverage of a 100%-covered module — worth a quick per-deletion check. Entry-point scripts (`__main__.py`, `cli.py`, `tray.py`) are the easy lever if Task 8 ends up short: excluding them from `--cov=recap` measurement via `.coveragerc` would add ~10 pp. But don't pull that lever yet; see if Tasks 2-5's real test coverage gets us to a comfortable cushion (~75%+) first.
