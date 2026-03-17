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
├── recap/
│   ├── __init__.py         # Package root — docstring only
│   ├── __main__.py         # Entry point for `python -m recap` (imports recap.cli.main)
│   ├── config.py           # YAML config loading: RecapConfig, WhisperXConfig, TodoistConfig, ClaudeConfig
│   ├── frames.py           # Frame extraction from video via ffmpeg scene detection (subprocess)
│   └── models.py           # Dataclasses: Participant, MeetingMetadata, Utterance, TranscriptResult, AnalysisResult, etc.
└── tests/
    ├── __init__.py         # Test package marker
    ├── conftest.py         # Shared fixtures: tmp_vault, tmp_recordings, tmp_frames
    ├── test_config.py      # Tests for YAML config loading and derived vault paths
    ├── test_frames.py      # Tests for frame extraction (mocked subprocess calls)
    └── test_models.py      # Tests for all data models and their from_dict/to_labelled_text methods
```

## Key Relationships

- `recap/__main__.py` imports `recap.cli.main` (not yet created — Task 4+)
- `recap/models.py` is the foundation — every pipeline module imports its dataclasses
- `recap/config.py` is used by every pipeline module; `load_config()` reads `config.yaml` and returns `RecapConfig`
- `config.example.yaml` documents all config keys; `config.yaml` is gitignored (contains secrets)
- `pyproject.toml` defines optional extras: `ml` (whisperx), `todoist`, `dev` (pytest)
- Test fixtures in `conftest.py` mirror vault structure: `Work/Meetings/`, `Work/People/`, `Work/Companies/`
- `recap/frames.py` is independent — uses only stdlib (subprocess, pathlib, dataclasses); no imports from other recap modules
- PLAN.md references tech stack decisions tracked in `~/.claude/projects/.../memory/meeting-tool-tech-stack.md`
