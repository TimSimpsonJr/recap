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
│   ├── analyze.py          # Claude Code CLI analysis: prompt building, JSON parsing, retry logic
│   ├── frames.py           # Frame extraction from video via ffmpeg scene detection (subprocess)
│   ├── models.py           # Dataclasses: Participant, MeetingMetadata, Utterance, TranscriptResult, AnalysisResult, etc.
│   └── transcribe.py       # WhisperX transcription + diarization; graceful ImportError if whisperx not installed
└── tests/
    ├── __init__.py         # Test package marker
    ├── conftest.py         # Shared fixtures: tmp_vault, tmp_recordings, tmp_frames
    ├── test_analyze.py     # Tests for Claude analysis module (mocked subprocess)
    ├── test_config.py      # Tests for YAML config loading and derived vault paths
    ├── test_frames.py      # Tests for frame extraction (mocked subprocess calls)
    ├── test_models.py      # Tests for all data models and their from_dict/to_labelled_text methods
    └── test_transcribe.py  # Tests for WhisperX transcription (mocked whisperx module)
```

## Key Relationships

- `recap/__main__.py` imports `recap.cli.main` (not yet created — Task 4+)
- `recap/models.py` is the foundation — every pipeline module imports its dataclasses
- `recap/config.py` is used by every pipeline module; `load_config()` reads `config.yaml` and returns `RecapConfig`
- `config.example.yaml` documents all config keys; `config.yaml` is gitignored (contains secrets)
- `pyproject.toml` defines optional extras: `ml` (whisperx), `todoist`, `dev` (pytest)
- Test fixtures in `conftest.py` mirror vault structure: `Work/Meetings/`, `Work/People/`, `Work/Companies/`
- `recap/frames.py` is independent — uses only stdlib (subprocess, pathlib, dataclasses); no imports from other recap modules
- `recap/transcribe.py` imports `recap.models` (Utterance, TranscriptResult); whisperx is optional (try/except ImportError)
- `recap/analyze.py` imports `recap.models` (AnalysisResult, MeetingMetadata, TranscriptResult); spawns `claude --print` as subprocess
- PLAN.md references tech stack decisions tracked in `~/.claude/projects/.../memory/meeting-tool-tech-stack.md`
