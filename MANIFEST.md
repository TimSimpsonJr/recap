# Recap — Structural Map

## Stack

- **Language:** Python 3.10+ (PyYAML, python-dotenv); pivoting to Python daemon + Obsidian plugin
- **Pipeline:** Claude CLI for meeting analysis, Obsidian vault writer for output
- **Browser extension:** Chrome/Edge MV3 for meeting URL detection (Zoom, Meet, Teams, Zoho)

## Structure

```
├── recap/                                   # Python pipeline package
│   ├── __init__.py / __main__.py            # Package init + `python -m recap` entry
│   ├── cli.py                               # CLI argument parsing and dispatch
│   ├── config.py                            # YAML config loader with env var interpolation
│   ├── pipeline.py                          # Stage-tracked orchestrator with status.json
│   ├── analyze.py                           # Claude CLI invocation for meeting analysis
│   ├── vault.py                             # Obsidian vault note writer (markdown output)
│   ├── models.py                            # Data models (MeetingMetadata, TranscriptSegment, etc.)
│   └── errors.py                            # Typed exceptions with actionable user messages
├── prompts/                                 # Claude prompt templates
│   ├── meeting_analysis.md                  # Main analysis prompt (summary, actions, decisions)
│   └── meeting_briefing.md                  # Pre-meeting briefing prompt
├── extension/                               # Chrome/Edge MV3 meeting URL detector
│   ├── manifest.json                        # Extension manifest (permissions, content scripts)
│   ├── background.js                        # Service worker: meeting URL detection + signaling
│   ├── content.js                           # Content script stub (reserved for future use)
│   ├── options.html / options.js            # Extension settings page
│   └── icons/                               # Extension icons (16, 48, 128px)
├── tests/                                   # Pytest test suite
│   ├── conftest.py                          # Shared fixtures (tmp dirs, mock config, metadata)
│   ├── fixtures/                            # Test data (config.yaml, test-metadata.json)
│   ├── test_pipeline.py                     # Pipeline orchestration tests
│   ├── test_pipeline_pause.py               # Pipeline pause/resume behavior
│   ├── test_pipeline_waiting.py             # Pipeline wait-for-input states
│   ├── test_pipeline_screenshot_extraction.py  # Screenshot extraction stage tests
│   ├── test_analyze.py                      # Claude analysis invocation tests
│   ├── test_vault.py                        # Vault note writer tests
│   ├── test_config.py                       # Config loading + validation tests
│   ├── test_cli.py                          # CLI argument parsing tests
│   ├── test_errors.py                       # Error mapping tests
│   ├── test_models.py                       # Data model tests
│   ├── test_participant_extraction.py       # Participant parsing from transcripts
│   └── test_speaker_labels.py              # Speaker label normalization tests
├── docs/plans/                              # Design docs + phased implementation plans
│   ├── 2026-04-13-implementation-overview.md       # 10-phase roadmap overview
│   ├── 2026-04-13-obsidian-plugin-architecture.md  # Plugin architecture design
│   ├── 2026-04-13-phase-{0..9}-*.md               # Individual phase plans
│   └── (legacy plans from Tauri era)               # Historical reference
├── config.example.yaml                      # Pipeline config template
├── pyproject.toml                           # Python project config (hatch, pytest, uv)
├── run_pipeline.py                          # Convenience script for running pipeline
├── .reap/genome/                            # Cortex project genome (principles, conventions, domain)
└── PLAN.md                                  # High-level project plan
```

## Key Relationships

- `pipeline.py` orchestrates stages, writes `status.json` per stage; `--from`/`--only` enable retry from any point
- `analyze.py` reads prompt templates from `prompts/` and invokes Claude CLI with meeting transcript
- `vault.py` consumes `analyze.py` output and writes structured markdown to the configured Obsidian vault
- `config.py` loads `config.example.yaml`-shaped files with env var interpolation; consumed by all pipeline stages
- `errors.py` maps exceptions to user-facing messages that reference specific config fields to fix
- `models.py` defines shared data structures used across `pipeline.py`, `analyze.py`, and `vault.py`
- `extension/background.js` detects meeting URLs and will signal the future Python daemon (Phase 4)
- `docs/plans/2026-04-13-*` define the 10-phase roadmap: daemon (1), recording (2), pipeline (3), detection (4), OAuth (5), plugin core (6), plugin advanced (7), streaming (8), packaging (9)
- `tests/conftest.py` provides shared fixtures; test files mirror `recap/` module structure
