# Core Pipeline Design — Phase 2

## Scope

CLI-only end-to-end pipeline: audio/video file + meeting metadata JSON → transcribed, diarized, analyzed → Obsidian vault meeting notes + Todoist tasks + people/company profile stubs.

Not used standalone — designed as a Python package with clean interfaces for future Tauri app integration. CLI is a test harness only.

## Architecture

Python package (`recap/`) with well-defined modules. Sequential pipeline — each stage depends on the previous.

### Package Structure

```
recap/
├── __init__.py
├── models.py          # Dataclasses for all data types
├── config.py          # Config loading from config.yaml
├── transcribe.py      # WhisperX: audio → diarized transcript
├── frames.py          # ffmpeg scene detection: video → key frames
├── analyze.py         # Claude Code CLI: transcript + metadata → analysis JSON
├── vault.py           # Obsidian note generation + profile stubs + previous meeting search
├── todoist.py         # Todoist REST API: create tasks from action items
├── pipeline.py        # Orchestrator: run(audio_path, metadata_path, config)
└── cli.py             # Test harness: python -m recap process <audio> <metadata>

prompts/
├── meeting_analysis.md    # Main analysis prompt
└── screenshot_caption.md  # Frame captioning prompt (deferred)

tests/
└── ...

config.example.yaml
```

### Dependencies

- **uv** for dependency management (venvs, lockfiles, CUDA package resolution)
- **WhisperX** — transcription + diarization (wraps faster-whisper + Pyannote)
- **ffmpeg** — frame extraction via scene detection
- **todoist-api-python** — Todoist REST API SDK
- **PyYAML** — config loading
- **Python 3.10+**

## Data Flow

```
Input:
  audio/video file (mp4, webm, wav, etc.)
  meeting.json (title, date, participants, platform)

Pipeline:
  1. transcribe.py
     WhisperX large-v3 on CUDA → diarized transcript (SPEAKER_00/01 labels)
     Saves transcript JSON to recordings path for re-analysis

  2. frames.py (skip if audio-only)
     ffmpeg scene detection (select='gt(scene,0.3)')
     Extracts key frames as .png to frames path
     Returns frame paths + timestamps

  3. analyze.py
     Loads meeting_analysis.md prompt template
     Injects: transcript, metadata (participant roster)
     Spawns `claude --print --output-format json`
     Claude maps speakers to roster names from conversational context
     Retries with exponential backoff (3 attempts: 2s, 8s, 30s)
     Returns AnalysisResult

  4. vault.py
     Moves recording to recordings path (YYYY-MM-DD-slug.ext)
     Writes meeting note to Tim's Vault/Work/Meetings/
     Searches existing notes for previous meeting (participant overlap)
     Creates people profile stubs (create-if-not-exists)
     Creates company profile stubs (create-if-not-exists)
     Embeds frames with timestamp labels (no AI captions yet)

  5. todoist.py
     Filters action items to user's tasks only (config.user_name)
     Creates tasks in configured project (mapped by meeting type)
     Uses obsidian:// URIs for meeting note links
     On failure: warns, saves to retry file, pipeline continues
```

## Data Models

### MeetingMetadata (input JSON)

```json
{
  "title": "Project Kickoff with Acme Corp",
  "date": "2026-03-16",
  "participants": [
    { "name": "Tim", "email": "tim@example.com" },
    { "name": "Jane Smith", "email": "jane@acme.com" }
  ],
  "platform": "zoom"
}
```

### Claude Analysis Output Schema

```json
{
  "speaker_mapping": {
    "SPEAKER_00": "Tim",
    "SPEAKER_01": "Jane Smith"
  },
  "meeting_type": "client-call",
  "summary": "2-3 sentence summary",
  "key_points": [
    { "topic": "Budget Review", "detail": "..." }
  ],
  "decisions": [
    { "decision": "...", "made_by": "Jane Smith" }
  ],
  "action_items": [
    {
      "assignee": "Tim",
      "description": "Send proposal by Friday",
      "due_date": "2026-03-20",
      "priority": "high"
    }
  ],
  "follow_ups": [
    { "item": "...", "context": "..." }
  ],
  "relationship_notes": "Context about working relationship (1:1 only, null otherwise)",
  "people": [
    { "name": "Jane Smith", "company": "Acme Corp", "role": "VP of Engineering" }
  ],
  "companies": [
    { "name": "Acme Corp", "industry": "SaaS" }
  ]
}
```

Nullable fields: `decisions`, `follow_ups`, `relationship_notes`. vault.py uses null/empty to omit conditional sections.

### Core Dataclasses (models.py)

- `MeetingMetadata` — title, date, participants, platform
- `Participant` — name, email
- `Utterance` — speaker label, start time, end time, text
- `TranscriptResult` — list of Utterances, raw text, language
- `AnalysisResult` — mirrors the Claude JSON schema above
- `ActionItem` — assignee, description, due_date, priority
- `ProfileStub` — name, company, role, key topics

## Meeting Note Generation

**Filename:** `YYYY-MM-DD - {title}.md`

**Frontmatter:**
```yaml
date: 2026-03-16
participants:
  - "[[Tim]]"
  - "[[Jane Smith]]"
companies:
  - "[[Acme Corp]]"
platform: zoom
duration: 45m
recording: C:/Users/tim/recap-data/recordings/2026-03-16-project-kickoff.mp4
type: client-call
tags:
  - meeting/client-call
```

- `companies` is a list (supports multi-company meetings)
- Duration calculated from audio file length
- Recording path is absolute (fix with find-and-replace when moving drives)
- Tags derived from Claude's `meeting_type` inference

**Conditional sections** (included only when Claude returns non-null data):
- Decisions Made
- Follow-up Required
- Relationship Notes (1:1 meetings only)
- Previous Meeting (when vault search finds a match)

**Extracted frames:** embedded as `![[filename.png]]` with timestamp labels, no AI captions.

**Profile stubs:** `vault.py` checks if `Work/People/{name}.md` or `Work/Companies/{name}.md` exists. If not, creates a minimal stub with frontmatter and empty sections. No merge, no update to existing profiles. Accepts that duplicates may occur (e.g., "Jane" vs "Jane Smith").

**Previous meeting linking:** Scans vault meeting files, parses frontmatter for participants, finds most recent note with significant participant overlap.

## Todoist Integration

**One-way only** (Phase 2). Completion sync back to vault is Phase 6.

- Only user's action items go to Todoist (filtered by `config.user_name`)
- Project mapping by meeting type in config:
  ```yaml
  todoist:
    default_project: "Recap"
    project_map:
      standup: "Sprint Tasks"
      client-call: "Client Work"
      planning: "Sprint Tasks"
      1:1: "Recap"
  ```
- Task content: action item description
- Task description: obsidian:// URI linking back to the meeting note
- Due date: natural language from Claude's extraction
- Labels: `["recap"]`
- Idempotency: check for existing task with same content before creating

**Failure handling:** On API error, save pending tasks to `recap-data/todoist-retry.json`. CLI provides `recap retry-todoist` command.

## Speaker Mapping

No heuristic pre-mapping. Claude receives the raw diarized transcript (SPEAKER_00, SPEAKER_01, etc.) alongside the participant roster from metadata and maps speakers using conversational context (name mentions, introductions, role references).

## Config

```yaml
vault_path: "C:/Users/tim/OneDrive/Documents/Tim's Vault"
recordings_path: "C:/Users/tim/recap-data/recordings"
frames_path: "C:/Users/tim/recap-data/frames"
user_name: "Tim"

whisperx:
  model: "large-v3"
  device: "cuda"
  language: "en"

huggingface_token: "hf_..."

todoist:
  api_token: "..."
  default_project: "Recap"
  project_map:
    standup: "Sprint Tasks"
    client-call: "Client Work"

claude:
  command: "claude"
```

## Error Handling

| Stage | On failure | Retry? | Rationale |
|-------|-----------|--------|-----------|
| Transcription | Fail pipeline | No | Local/deterministic — retry won't help |
| Frame extraction | Warn, continue | No | Local/deterministic — note still valid without frames |
| Claude analysis | Retry with backoff | Yes (3 attempts: 2s, 8s, 30s) | Network/API — transient failures common |
| Vault writing | Fail pipeline | No | Local filesystem — primary output |
| Profile stubs | Warn, continue | No | Meeting note still valid without stubs |
| Todoist | Warn, save retry file | Yes (deferred) | Network/API — retry file for later |

Principle: retry network calls, don't retry local operations.

**Idempotency:** If a meeting note with the same filename exists, skip and warn.

## Logging

Python `logging` module with structured format. Each pipeline stage logs start/end/duration. Errors include full context (file paths, API responses). Log file written to `recap-data/logs/`.
