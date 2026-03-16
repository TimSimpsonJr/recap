# Recap — Structural Map

## Stack

- **Desktop app:** Tauri v2 (Rust backend + web frontend)
- **ML pipeline:** Python (Whisper large-v3, Pyannote 3.1)
- **AI analysis:** Claude Code CLI (subprocess)
- **Integrations:** Zoom API, Todoist API, Zoho Calendar API

## Structure

```
recap/
├── .gitignore              # Git ignore rules for Tauri, Node, Python, recordings
├── MANIFEST.md             # This file — structural map
└── PLAN.md                 # Full implementation plan with architecture, phases, and decisions
```

## Key Relationships

- PLAN.md references tech stack decisions tracked in `~/.claude/projects/.../memory/meeting-tool-tech-stack.md`
- Vault output targets `Tim's Vault/Work/Meetings/`, `Work/People/`, `Work/Companies/`
- Todoist syncs bidirectionally with vault action item checkboxes via scheduled task
