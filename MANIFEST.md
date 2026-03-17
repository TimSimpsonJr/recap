# Recap — Structural Map

## Stack

- **Language:** Python 3.10+ (managed by uv)
- **ML pipeline:** WhisperX (optional), Pyannote 3.1
- **AI analysis:** Claude Code CLI (subprocess)
- **Integrations:** Todoist API (optional), Obsidian vault output

## Structure

```
recap/
├── .gitignore              # Git ignore rules for Tauri, Node, Python, recordings, secrets
├── MANIFEST.md             # This file — structural map
├── PLAN.md                 # Full implementation plan with architecture, phases, and decisions
├── pyproject.toml          # Project metadata, dependencies, pytest config (uv-managed)
├── config.example.yaml     # Example configuration (vault path, API tokens, WhisperX settings)
├── prompts/
│   └── meeting_analysis.md # Claude analysis prompt template with {{participants}} and {{transcript}} placeholders
├── docs/
│   └── plans/              # Design docs and implementation plans
├── recap/
│   ├── __init__.py         # Package root — docstring only
│   ├── __main__.py         # Entry point for `python -m recap` (imports recap.cli.main)
│   ├── cli.py              # CLI test harness: argparse subcommands (process, retry-todoist), logging setup
│   ├── config.py           # YAML config loading: RecapConfig, WhisperXConfig, TodoistConfig, ClaudeConfig
│   ├── analyze.py          # Claude Code CLI analysis: prompt building, JSON parsing, retry logic
│   ├── frames.py           # Frame extraction from video via ffmpeg scene detection (subprocess)
│   ├── models.py           # Dataclasses: Participant, MeetingMetadata, Utterance, TranscriptResult, AnalysisResult, etc.
│   ├── pipeline.py         # Pipeline orchestrator: ties transcribe, frames, analyze, vault, todoist together
│   ├── todoist.py          # Todoist task creation from action items; obsidian URI linking, retry file persistence
│   ├── transcribe.py       # WhisperX transcription + diarization; graceful ImportError if whisperx not installed
│   └── vault.py            # Obsidian vault writing: meeting notes, profile stubs (people/companies), previous meeting search
└── tests/
    ├── __init__.py         # Test package marker
    ├── conftest.py         # Shared fixtures: tmp_vault, tmp_recordings, tmp_frames
    ├── test_cli.py         # Tests for CLI arg parsing and process command (mocked pipeline)
    ├── test_analyze.py     # Tests for Claude analysis module (mocked subprocess)
    ├── test_config.py      # Tests for YAML config loading and derived vault paths
    ├── test_frames.py      # Tests for frame extraction (mocked subprocess calls)
    ├── test_models.py      # Tests for all data models and their from_dict/to_labelled_text methods
    ├── test_pipeline.py    # Tests for pipeline orchestrator (mocked transcribe, analyze, frames, todoist)
    ├── test_todoist.py     # Tests for Todoist integration (mocked API, retry file, filtering, URI building)
    ├── test_transcribe.py  # Tests for WhisperX transcription (mocked whisperx module)
    └── test_vault.py       # Tests for vault: meeting notes, profile stubs, previous meeting search
```

## Key Relationships

- `recap/__main__.py` imports `recap.cli.main` — the CLI entry point
- `recap/cli.py` imports `recap.config.load_config` and `recap.pipeline.run_pipeline`; retry-todoist lazily imports `recap.todoist`
- `recap/models.py` is the foundation — every pipeline module imports its dataclasses
- `recap/config.py` is used by every pipeline module; `load_config()` reads `config.yaml` and returns `RecapConfig`
- `config.example.yaml` documents all config keys; `config.yaml` is gitignored (contains secrets)
- `pyproject.toml` defines optional extras: `ml` (whisperx), `todoist`, `dev` (pytest)
- Test fixtures in `conftest.py` mirror vault structure: `Work/Meetings/`, `Work/People/`, `Work/Companies/`
- `recap/frames.py` is independent — uses only stdlib (subprocess, pathlib, dataclasses); no imports from other recap modules
- `recap/transcribe.py` imports `recap.models` (Utterance, TranscriptResult); whisperx is optional (try/except ImportError)
- `recap/analyze.py` imports `recap.models` (AnalysisResult, MeetingMetadata, TranscriptResult); spawns `claude --print` as subprocess
- `recap/todoist.py` imports `recap.models` (ActionItem); wraps `todoist-api-python` with try/except ImportError (same pattern as transcribe.py)
- `recap/vault.py` imports `recap.models` (AnalysisResult, MeetingMetadata, ProfileStub) and `recap.frames` (FrameResult); `_slugify` is reused by pipeline.py
- `recap/pipeline.py` is the top-level orchestrator — imports from all other recap modules (transcribe, frames, analyze, vault, todoist, config, models)
- `recap/pipeline.py` gracefully degrades: todoist failures save a retry file, frame extraction failures are logged and skipped
- `prompts/meeting_analysis.md` is loaded by `recap/pipeline.py` via `pathlib.Path(__file__).parent.parent / "prompts"` — template is outside the package
- PLAN.md references tech stack decisions tracked in `~/.claude/projects/.../memory/meeting-tool-tech-stack.md`
