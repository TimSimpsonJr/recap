# Issue #28 — Speaker Correction + Identity Model Design

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:writing-plans` to produce the implementation plan from this design.

**Goal:** Enable clean correction of any speaker (unresolved `SPEAKER_XX` or already-named) with a stable diarized identity, end-to-end path resolution, first-pass auto-labeling on the unambiguous case, and a gated contact-creation flow that converges duplicate aliases onto canonical identities via the enrichment data #29 already populates.

**Architecture:** `Utterance` gains an immutable `speaker_id` alongside the existing mutable `speaker` display label. Correction is the single commit point for contacts: typed names run through an 8-step resolution engine on the plugin side, the daemon applies contact mutations (with live config refresh) + creates People stubs via the existing canonical template, and reprocess re-canonicalizes participants against the refreshed `known_contacts` before analyze + export. Browser enrichment (#29) already feeds `metadata.participants`; #28 makes that data do dedup work at correction time.

**Tech Stack:** Python 3.12 async daemon (aiohttp, ruamel.yaml); Obsidian plugin (TypeScript + Vitest); pytest + manual acceptance for testing.

---

## 1. Architecture overview

Five input surfaces, four processing components, four output surfaces.

```
Inputs:                              Components:                   Outputs:
┌─────────────────────────┐
│ Transcript speakers     │ ─┐
│ (speaker_id + display)  │  │
└─────────────────────────┘  │      ┌─────────────────────────┐    ┌──────────────────────────┐
┌─────────────────────────┐  │      │ Correction Modal        │    │ .speakers.json           │
│ metadata.participants   │ ─┼────► │ (plugin)                │ ──►│ (speaker_id → display)   │
│ (#29 enrichment output) │  │      │ + resolution engine     │    └──────────────────────────┘
└─────────────────────────┘  │      └─────────────────────────┘    ┌──────────────────────────┐
┌─────────────────────────┐  │                 │                   │ known_contacts           │
│ known_contacts          │ ─┤                 │ resolution plan   │ (+ aliases, + email)     │
│ (+ aliases, + email)    │  │                 ▼                   │ via ruamel PATCH         │
└─────────────────────────┘  │      ┌─────────────────────────┐    └──────────────────────────┘
┌─────────────────────────┐  │      │ Save Commit             │ ──►┌──────────────────────────┐
│ People note basenames   │ ─┤      │ (plugin → daemon)       │    │ <org-subfolder>/         │
│ (vault scan)            │  │      │ + daemon contact writes │    │   People/<name>.md stubs │
└─────────────────────────┘  │      │ + daemon stub creation  │    └──────────────────────────┘
┌─────────────────────────┐  │      │ + daemon live refresh   │    ┌──────────────────────────┐
│ Company note basenames  │ ─┘      └─────────────────────────┘    │ Reprocess trigger        │
│ (ineligibility guard)   │                                        │ (analyze + export with   │
└─────────────────────────┘                                        │  effective_participants) │
                                                                   └──────────────────────────┘
```

### Data flow at correction save

1. Plugin fetches `GET /api/meetings/{stem}/speakers` — returns `[{speaker_id, display}]` from the transcript artifact.
2. Plugin gathers the other four input surfaces: `metadata.participants` (frontmatter), `known_contacts` (`/api/config`), People notes + Company notes (vault scan by `org-subfolder`).
3. User types names in the modal. As each field changes/blurs, plugin computes a **resolution plan** per entry with four terminal outcomes: `link_to_existing` / `create_new_contact` / `near_match_ambiguous` / `ineligible`.
4. Near-match triggers an inline "Did you mean X? [Use existing] [Create new anyway]"; ineligibility (`SPEAKER_*`, `Unknown Speaker`, Company-collision, multi-person form, parenthetical after strip-and-retry) refuses save.
5. On save:
   - Plugin POSTs `{stem, mapping, contact_mutations, org}` to `/api/meetings/speakers`.
   - Daemon applies contact mutations atomically (ruamel round-trip preserves user's custom blocks + comments), refreshes live config + propagates to cached subservice references.
   - Daemon writes `.speakers.json` keyed by `speaker_id`.
   - Daemon creates any new People stubs via existing `_generate_person_stub` canonical template (idempotent, no clobber).
   - Daemon triggers reprocess from `analyze` stage (existing machinery; server docstring typo at [server.py:576](recap/daemon/server.py:576) says "export" but code triggers from "analyze" — fix during implementation).
6. Reprocess rewrites transcript's mutable `speaker` labels via `_apply_speaker_mapping` keyed on `speaker_id`, re-canonicalizes `metadata.participants` against refreshed `known_contacts`, builds an **ephemeral `MeetingMetadata`** with merged `effective_participants`, and passes that into both `analyze()` and `build_canonical_frontmatter()`. The sidecar stays untouched.

### First-pass auto-relabel (new meetings)

Between diarize and analyze stages, `_maybe_apply_first_pass_relabel` writes `.speakers.json` with `{speaker_id: name}` **if and only if** exactly one distinct `speaker_id` in the transcript AND exactly one eligible participant in `metadata.participants`. Otherwise pipeline proceeds with diarized IDs, awaiting user correction.

### Ownership split

- **Daemon owns:** transcript artifact schema, `speaker_id`, path resolution, `.speakers.json`, `known_contacts` config, reprocess pipeline, People stub creation via canonical template, live config refresh.
- **Plugin owns:** modal UI, client-side resolution engine (pure function), vault scan for autocomplete + ineligibility guards, speaker list fetch.

---

## 2. Schema changes

### 2.1 `Utterance` + explicit `from_dict`

```python
@dataclass
class Utterance:
    speaker_id: str  # immutable diarized identity, written once by diarize
    speaker: str     # mutable display label; rewritten by _apply_speaker_mapping
    start: float
    end: float
    text: str

    @classmethod
    def from_dict(cls, data: dict) -> Utterance:
        speaker = data["speaker"]
        return cls(
            speaker_id=data.get("speaker_id", speaker),  # backfill pre-#28 artifacts
            speaker=speaker,
            start=data["start"],
            end=data["end"],
            text=data["text"],
        )
```

### 2.2 `_apply_speaker_mapping` keyed by `speaker_id`

```python
def _apply_speaker_mapping(transcript, mapping: dict[str, str]) -> TranscriptResult:
    """Keys are speaker_id values; values are new display labels.
    speaker_id passes through unchanged on every utterance."""
    new_utterances = [
        Utterance(
            speaker_id=u.speaker_id,
            speaker=mapping.get(u.speaker_id, u.speaker),
            start=u.start, end=u.end, text=u.text,
        )
        for u in transcript.utterances
    ]
    return TranscriptResult(...)
```

### 2.3 `KnownContact` with `aliases` + `email`

```python
@dataclass
class KnownContact:
    name: str                                          # canonical; People note basename
    display_name: str                                  # preferred visible label
    aliases: list[str] = field(default_factory=list)  # observed variants
    email: str | None = None                           # primary dedup signal
```

YAML shape:
```yaml
known-contacts:
  - name: Sean Mooney
    display-name: Sean Mooney
    email: sean@example.com
    aliases:
      - Sean M.
      - Sean
```

### 2.4 `match_known_contacts` — email-first, alias-aware, empty-skip

```python
def match_known_contacts(
    observed: list[Participant],
    contacts: list[KnownContact],
) -> list[Participant]:
    """Canonicalize. Precedence:
       1. Email match (case-insensitive exact)
       2. Normalized name match against name / display_name / aliases
       3. Passthrough
    """
    by_email = {c.email.casefold(): c for c in contacts if c.email}
    by_name: dict[str, KnownContact] = {}
    for c in contacts:
        if c.name:
            by_name[_normalize(c.name)] = c
        if c.display_name:
            by_name[_normalize(c.display_name)] = c
        for alias in c.aliases:
            if alias:
                by_name[_normalize(alias)] = c

    out = []
    for p in observed:
        match = by_email.get(p.email.casefold()) if p.email else None
        if match is None:
            match = by_name.get(_normalize(p.name))
        if match is not None:
            out.append(Participant(name=match.name, email=p.email or match.email))
        else:
            out.append(p)
    return out
```

`_normalize` is the shared helper: casefold + strip whitespace + collapse internal whitespace + strip `.` `,`.

### 2.5 `TranscriptResult.from_dict` delegates

```python
@classmethod
def from_dict(cls, data: dict) -> TranscriptResult:
    return cls(
        utterances=[Utterance.from_dict(u) for u in data.get("utterances", [])],
        raw_text=data.get("raw_text", ""),
        language=data.get("language", "en"),
    )
```

### 2.6 Migration summary

| Artifact | Before | After | Migration |
|---|---|---|---|
| `<stem>.transcript.json` | `speaker` only | `speaker_id` + `speaker` | `Utterance.from_dict` backfills on load |
| `.speakers.json` | `{display → new_display}` | `{speaker_id → new_display}` | Legacy accepted; first post-#28 save rewrites keyed by `speaker_id`. No automatic replay on load. |
| `config.yaml known-contacts` | `{name, display-name}` | `+ aliases?, + email?` | ruamel defaults missing to `[]` / `None` |
| `match_known_contacts` callers | `list[str]` | `list[Participant]` | callsite refactor in enrichment.py |

### 2.7 Historical caveat

For transcripts corrected pre-#28, backfill makes `speaker_id = current speaker label` rather than the original diarized ID. Re-correction still works against these backfilled IDs, but the original `SPEAKER_XX` is unrecoverable. Unavoidable; documented.

---

## 3. Daemon-side changes

### 3.1 Path resolver (shared helper)

```python
# recap/artifacts.py
def resolve_recording_path(
    recordings_path: Path, stem: str,
) -> Path | None:
    """FLAC → M4A precedence. None if neither exists.
    Used by /api/meetings/speakers and /api/recordings/{stem}/clip
    so they agree on which artifact is source of truth."""
    flac = recordings_path / f"{stem}.flac"
    if flac.exists(): return flac
    m4a = recordings_path / f"{stem}.m4a"
    if m4a.exists(): return m4a
    return None
```

Clip endpoint inline resolution extracted to this helper.

### 3.2 `GET /api/meetings/{stem}/speakers`

New endpoint. Returns distinct `(speaker_id, display)` pairs in first-seen order from the transcript artifact. Uses existing `load_transcript` / `transcript_path` helpers from `artifacts.py`. Bearer auth via existing `/api/*` middleware.

### 3.3 `POST /api/meetings/speakers` (amended)

Contract accepts both `stem` (preferred) and `recording_path` (legacy):

```python
stem = body.get("stem")
legacy_path = body.get("recording_path")

if stem:
    audio_path = resolve_recording_path(daemon.config.recordings_path, stem)
    if audio_path is None:
        return web.json_response({"error": "recording not found"}, status=404)
elif legacy_path:
    audio_path = Path(legacy_path)
else:
    return web.json_response({"error": "missing stem or recording_path"}, status=400)
```

Body adds optional `contact_mutations`:
```typescript
contact_mutations: Array<
    | {action: "create"; name: string; display_name: string; email?: string}
    | {action: "add_alias"; name: string; alias: string}
>;
```

Handler ordering: validate body → resolve path → apply contact mutations (atomic, validate before write, refresh config on success) → create People stubs for any `create` mutations → write `.speakers.json` → trigger reprocess from `analyze` stage.

### 3.4 Contact mutation application

```python
def _apply_contact_mutations(daemon: Daemon, mutations: list[dict]) -> None:
    """Apply then refresh.

    Guarantees:
      - File write is atomic (temp + rename).
      - End-to-end apply+refresh is NOT atomic: if file write succeeds
        but refresh_config() fails, disk is correct, memory stale.
        User sees 500; manual restart resolves.
      - Steps 1-3 (load, stage, validate) never touch disk if they raise.
    """
    with daemon.config_lock:
        yaml_doc = _load_ruamel(daemon.config_path)
        for m in mutations:
            _apply_single_mutation(yaml_doc, m)
        _validate_via_existing_yaml_config_validator(yaml_doc)
        _atomic_write_ruamel(daemon.config_path, yaml_doc)
        daemon.refresh_config()
```

Validation seam: use the same validator the `/api/config` PATCH path uses — exact shape TBD at implementation, since a shallow `dict()` cast on a ruamel document may not preserve nested `CommentedMap`/`CommentedSeq` structure.

### 3.5 First-pass relabel step

```python
def _maybe_apply_first_pass_relabel(
    audio_path: Path,
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
) -> None:
    """Write .speakers.json auto-mapping only when:
      - exactly one distinct speaker_id in transcript, AND
      - exactly one eligible participant in metadata.participants.
    Honors existing .speakers.json (respects user corrections).
    Wired between diarize and analyze stages."""
```

Runs synchronously in the pipeline; disk-write failure is logged and non-blocking.

### 3.6 Clip endpoint keys on `speaker_id`

Query param `speaker_id` (not `speaker`). Match on `u.speaker_id` with backfill. Clip cache filename uses `speaker_id` so cached clips survive display relabels.

### 3.7 Daemon config refresh + consumer propagation

Starts with the simpler shape (preferred by reviewer):

```python
def refresh_config(self) -> None:
    """Reload config from disk and propagate to known subservices."""
    new_config = load_daemon_config(self.config_path)
    self.config = new_config
    # Explicit known consumers; registry can emerge later if needed.
    if self.detector is not None:
        self.detector.on_config_reloaded(new_config)
    # Audit every cached-config holder during implementation.
```

### 3.8 `_ensure_people_stub`

```python
def _ensure_people_stub(daemon: Daemon, org: str, name: str) -> None:
    """Idempotent canonical-template stub writer. Uses existing
    _generate_person_stub from recap/vault.py (no duplication)."""
    org_config = daemon.config.org_by_slug(org)
    if org_config is None:
        raise ValueError(f"unknown org: {org}")
    vault_path = Path(daemon.config.vault_path)
    org_subfolder = org_config.resolve_subfolder(vault_path)
    people_dir = org_subfolder / "People"
    stub_path = people_dir / f"{safe_note_title(name)}.md"
    if stub_path.exists():
        return  # no clobber
    people_dir.mkdir(parents=True, exist_ok=True)
    content = _generate_person_stub(ProfileStub(name=name))
    stub_path.write_text(content)
```

### 3.9 Server docstring cleanup

[server.py:576](recap/daemon/server.py:576) docstring says "reprocess from export"; code triggers from `analyze` at [server.py:612, :622](recap/daemon/server.py:612). Fix during implementation.

---

## 4. Plugin-side changes

### 4.1 DaemonClient additions

```typescript
async getMeetingSpeakers(stem: string): Promise<Array<{speaker_id: string; display: string}>>;

async saveSpeakerCorrections(params: {
    stem: string;
    mapping: Record<string, string>;  // speaker_id → display name
    contact_mutations: ContactMutation[];
    org: string;
}): Promise<void>;

type ContactMutation =
    | {action: "create"; name: string; display_name: string; email?: string}
    | {action: "add_alias"; name: string; alias: string};
```

Clip fetch caller updated to pass `speaker_id`.

### 4.2 Entry point — stop regex-scanning note body

`openSpeakerCorrection` in `main.ts` fetches speakers from daemon regardless of note body content. Reads both `org` and `org-subfolder` from frontmatter. Scans under `org-subfolder/People/` and `org-subfolder/Companies/`.

### 4.3 Modal — broadened to any speaker

Modal constructor takes: `speakers`, `peopleNames`, `companyNames`, `knownContacts`, `meetingParticipants`, `stem`, `org`, `orgSubfolder`, `client`. Row UI: current `speaker_id` + display, text input, audio clip button (keyed on `speaker_id`), inline resolution hint ("Links to X" / "Did you mean X?" / "Rename required: ..." / "Will create new contact and People note").

### 4.4 Client-side resolution engine

Pure function in `obsidian-recap/src/correction/resolve.ts`:

```typescript
type ResolutionPlan =
    | {kind: "link_to_existing"; canonical_name: string; requires_contact_create: boolean; email?: string}
    | {kind: "create_new_contact"; name: string; email?: string}
    | {kind: "near_match_ambiguous"; suggestion: string; typed: string}
    | {kind: "ineligible"; reason: string; typed: string};

function resolve(typed: string, ctx: ResolutionContext): ResolutionPlan {
    const normalized = normalize(typed);
    if (!normalized) return {kind: "ineligible", reason: "empty", typed};

    // Match attempts first (no ineligibility check yet).
    const linked = tryMatches(typed, normalized, ctx);
    if (linked) return linked;

    // Parenthetical strip-and-retry.
    const stripped = stripParenthetical(typed);
    if (stripped !== typed && normalize(stripped)) {
        const retried = tryMatches(stripped, normalize(stripped), ctx);
        if (retried) return retried;
    }

    // Initial-aware token near-match.
    const near = findNearMatch(normalized, ctx);
    if (near) return {kind: "near_match_ambiguous", suggestion: near, typed};

    // Ineligibility filter (after all match attempts fail).
    const ineligibility = checkIneligibility(typed, normalized, ctx);
    if (ineligibility) return ineligibility;

    // Create new.
    const participantMatch = ctx.meetingParticipants.find(
        p => normalize(p.name) === normalized && p.email,
    );
    return {kind: "create_new_contact", name: typed, email: participantMatch?.email};
}
```

`tryMatches` precedence: email-first → exact known_contact name/display/alias → exact People-note basename (marks `requires_contact_create=true`).

### 4.5 Near-match algorithm — initial-aware token subset

- Normalize both typed and candidate with `normalize()`.
- Tokenize on whitespace.
- First token must match exactly.
- Later tokens match exactly OR by initial (first character, case-insensitive).
- Candidates: `knownContacts.{name, display_name, aliases}` ∪ `peopleNames`.

Example: `Sean M.` → normalized `sean m` → first token `sean` matches `Sean Mooney`'s `sean`; second token `m` is initial of `mooney`. Match.

### 4.6 Ineligibility filter

Refuses silent creation when typed name (after strip-and-retry):
- Matches `^SPEAKER_\d+$`
- Matches `^Unknown Speaker\b`
- Matches empty / whitespace-only
- Still contains parentheticals (meaning strip-and-retry didn't help)
- Matches a Company note basename (company-collision guard, vault-aware)
- Is a multi-person form (contains `/` separator, e.g., `Ed/Ellen`)
- Matches obvious team/role labels (lightweight keyword list — implementation decides exact scope)

### 4.7 Save orchestration

```typescript
async onSubmit(): Promise<void> {
    // 1. Compute all plans; refuse save if any ineligible or ambiguous.
    // 2. Build mapping + contact_mutations.
    // 3. POST to daemon.
    // 4. Close modal + notice "reprocessing...".
    // Daemon handles stub creation; plugin is done after the POST.
}
```

No plugin-side stub writes. Plugin sends one POST; daemon atomically applies mutations + creates stubs + triggers reprocess.

---

## 5. Frontmatter re-derivation flow

### 5.1 `companies` — zero code change

Analyze re-runs on reprocess, LLM sees corrected transcript, `analysis.companies` reflects corrected context. [vault.py:114](recap/vault.py:114) unchanged.

### 5.2 `participants` — ephemeral effective list before analyze + export

On reprocess from analyze stage:

```python
# 1. Apply .speakers.json mapping to transcript.
mapping = _load_speakers_json(audio_path)
transcript = _apply_speaker_mapping(transcript, mapping)
save_transcript(audio_path, transcript)

# 2. Re-canonicalize enrichment participants against live (post-refresh) known_contacts.
canonical_participants = match_known_contacts(
    metadata.participants, daemon.config.known_contacts,
)

# 3. Build effective_participants: enrichment first (in order), then correction-derived.
effective_participants: list[Participant] = []
seen_names: set[str] = set()
for p in canonical_participants:
    if p.name not in seen_names:
        effective_participants.append(p)
        seen_names.add(p.name)
for u in transcript.utterances:
    if u.speaker in seen_names: continue
    if not _is_eligible_person_label(u.speaker): continue
    effective_participants.append(Participant(name=u.speaker, email=None))
    seen_names.add(u.speaker)

# 4. Ephemeral MeetingMetadata; sidecar untouched.
effective_metadata = replace(metadata, participants=effective_participants)

# 5. Feed into both analyze and export.
analysis = await analyze(transcript, effective_metadata, ...)
write_meeting_note(note_path, effective_metadata, analysis, transcript, ...)
```

### 5.3 Shared `_is_eligible_person_label`

Lives in `recap/identity.py`. Used by first-pass auto-relabel AND reprocess union AND (conceptually) client-side resolver. Daemon-side version accepts `SPEAKER_*`, `UNKNOWN*`, parenthetical, empty as ineligible. Client-side resolver extends with company-collision + multi-person form guards (needs vault scan the daemon doesn't have).

### 5.4 Known limitation

If enrichment has "Bob" (wrong) and correction says `SPEAKER_00 = Alice` (right), both appear in frontmatter. Enrichment is treated as ground truth for attendance; no way to know Bob is stale without user signal. Documented; user manually removes from note.

### 5.5 Post-recording re-canonicalization via live config

Step 2 above depends on `daemon.config.known_contacts` being live (post-refresh). Section 3.7's `refresh_config()` pathway guarantees this. Audit task in the implementation plan: verify every cached-config holder in the daemon participates in the refresh, or `match_known_contacts` in step 2 sees a stale list.

---

## 6. Error handling and migration

### 6.1 Daemon endpoint errors

**`GET /api/meetings/{stem}/speakers`:** 401 no-auth / 404 recording-not-found / 404 transcript-not-found / 500 JSON decode / 200 empty speakers / 503 shutdown.

**`POST /api/meetings/speakers`:** 401 / 400 missing fields / 400 malformed body / 404 stem-unresolved / 400 validate_from_stage fails / 500 contact mutation validation error (disk untouched) / 500 config refresh fails (disk committed, memory stale) / 500 stub creation fails (contacts committed, stubs partial) / 200 with 500-retry-safe idempotent state.

### 6.2 Atomicity (honest)

- **File write:** atomic via temp-file + rename.
- **Apply + refresh end-to-end:** NOT atomic. Disk can commit while in-memory stale → 500 + user restart.
- **Stub creation:** separate from config write. Idempotent retry is safe.

### 6.3 Migration

Load-boundary backfill handles pre-#28 transcripts (`Utterance.from_dict` defaults `speaker_id = speaker`). Legacy `.speakers.json` keyed by display accepted; first post-#28 save rewrites keyed by `speaker_id`.

### 6.4 Plugin errors

Modal doesn't open on daemon unreachable / `getMeetingSpeakers` fail. Save button disabled when any row's plan is `ineligible` or `near_match_ambiguous`. POST failure → `Notice` + modal stays open.

### 6.5 Concurrency

`config_lock` serializes contact mutations. Reprocess is fire-and-forget idempotent. Rapid-fire save is documented last-writer-wins (acceptable for single-user personal tool).

### 6.6 Merge-friendly invariants (for future [#37](https://github.com/TimSimpsonJr/recap/issues/37))

- `KnownContact.name` is the single canonical key. Aliases + email attach to it.
- Correction always writes canonical `name` into `.speakers.json` + transcript `speaker`, never an alias.
- No aliases in note bodies. No identity derivation from note body text.
- Future merge tool is a pure reference rewrite, not identity reconstruction.

---

## 7. Testing strategy

### 7.1 Test file matrix

| File | Scope | New / extended |
|---|---|---|
| `tests/test_models.py` | Utterance backfill, TranscriptResult delegation | extended |
| `tests/test_pipeline_speaker_mapping.py` | `_apply_speaker_mapping` speaker_id preservation | new |
| `tests/test_pipeline_first_pass_relabel.py` | Case A only, existing file respected, eligibility | new |
| `tests/test_pipeline_reprocess_participants.py` | effective_participants union, re-canonicalization, ephemeral metadata | new |
| `tests/test_identity.py` | `_is_eligible_person_label` | new |
| `tests/test_artifacts_path_resolver.py` | FLAC→M4A precedence | new |
| `tests/test_enrichment.py` | Email-first, alias-aware, empty-field skip | extended |
| `tests/test_daemon_server.py` | GET /speakers, POST /speakers stem-or-legacy, contact_mutations | extended |
| `tests/test_clip_endpoint.py` | speaker_id keying + cache filename | extended |
| `tests/test_daemon_config_mutations.py` | Atomicity, validation, refresh, subservice propagation | new |
| `tests/test_vault_people_stub.py` | `_ensure_people_stub` idempotency | new |
| `tests/test_speaker_correction_integration.py` | End-to-end round-trip | new |
| `obsidian-recap/src/correction/resolve.test.ts` | 8-step precedence | new (extends existing Vitest setup) |
| `obsidian-recap/src/correction/normalize.test.ts` | Shared normalize helper | new |

### 7.2 Manual acceptance checklist

New `docs/handoffs/YYYY-MM-DD-28-acceptance.md` covers real UIA / real vault / real user flows. 15 scenarios including: fresh-vault reset, first-pass auto-relabel happy path, unresolved SPEAKER correction, already-named rename, near-match accept, near-match decline + create, ineligibility refusal, parenthetical strip-and-retry, daemon-created canonical stubs, alias persistence across meetings, daemon restart survival, live config refresh without restart, legacy transcript migration.

### 7.3 JS test scope

Extend existing Vitest setup in `obsidian-recap/`. Tests cover pure functions (`resolve`, `normalize`, `checkIneligibility`, `findNearMatch`). Modal UI behavior stays in manual acceptance — no DOM-mock complexity.

---

## 8. Non-goals and future-compat seams

### 8.1 Non-goals

**Deferred to [#37](https://github.com/TimSimpsonJr/recap/issues/37):** duplicate merge/remediation for People and Companies.

**Deferred to future (untracked):**
- Channel/self provenance for first-pass Case B (1-on-1 with known user identity).
- Company alias learning.
- Voice fingerprinting, directory imports, bulk-apply corrections, undo history.

**Out of scope by design:**
- Retroactive rewrite of pre-#28 `.speakers.json` files.
- Cross-file atomicity for `.speakers.json` + `config.yaml` + stubs (each idempotent; retries resolve).

### 8.2 Future-compat seams preserved

| Seam | Enables |
|---|---|
| `speaker_id` / `speaker` split | Unlimited correction rounds, stable clips, future channel/self provenance |
| `KnownContact.aliases` + `email` | Alias learning at enrichment ingress, email dedup |
| Canonical `name` as single identity key | Future merge tool is pure reference rewrite |
| `daemon.refresh_config()` | Any future live config mutation path |
| Shared `_is_eligible_person_label` | Single-source semantics across pipeline + plugin |
| `effective_participants` ephemeral build | Sidecar stays immutable enrichment snapshot |

### 8.3 Locked decisions (one-line summary)

1. **Schema:** `Utterance.speaker_id` (immutable) + `speaker` (mutable). `KnownContact` + `aliases` + `email`.
2. **Path resolution:** daemon-side `resolve_recording_path(stem)`, FLAC→M4A, shared by clip + speakers endpoints.
3. **Identity persistence:** correction is single commit point. New names → daemon writes contact + canonical-template stub.
4. **Resolution precedence:** normalize → email-first → exact name/alias → People-note-only → strip-and-retry → initial-aware near-match → ineligibility → create new.
5. **First-pass relabel:** Case A only (1 speaker_id + 1 eligible participant).
6. **Re-derivation:** ephemeral `MeetingMetadata` with merged `effective_participants` before analyze.
7. **Atomicity:** file write atomic; end-to-end not atomic; partial-success documented and idempotent-retry-safe.
8. **Stub ownership:** daemon-side via existing canonical template.
9. **Testing:** extend existing Vitest + pytest; pure-function client tests; manual acceptance for UI.

---

## References

- Issue: [#28](https://github.com/TimSimpsonJr/recap/issues/28)
- Follow-up: [#37](https://github.com/TimSimpsonJr/recap/issues/37) (duplicate merge)
- Prerequisite: [#29](https://github.com/TimSimpsonJr/recap/issues/29) (enrichment; merged PR #36)
- Related: #30 (Teams detection, merged as #32), #27 (unscheduled meetings, merged as #34)
