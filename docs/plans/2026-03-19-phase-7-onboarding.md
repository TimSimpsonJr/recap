# Phase 7: Onboarding Flow — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** First-run onboarding wizard + inline dashboard checklist + config.yaml generation from settings + actionable pipeline errors.

**Architecture:** Full-screen wizard (4 steps) gates the app until required settings are configured. After completion, an inline checklist on the dashboard nudges optional integrations (OAuth, browser extension). Rust generates config.yaml from the settings store before each sidecar launch. Pipeline error messages are mapped to actionable guidance referencing specific Settings sections.

**Tech Stack:** Svelte 5 (runes), Tauri v2 plugin-store + plugin-stronghold, Rust serde_yaml, Python try/except error mapping

---

### Task 1: Add new settings fields

**Files:**
- Modify: `src/lib/stores/settings.ts:4-52`

**Step 1: Add fields to AppSettings interface and defaults**

Add these fields to the `AppSettings` interface at `settings.ts:4`:

```typescript
export interface AppSettings {
  // ... existing fields ...
  onboardingComplete: boolean;
  userName: string;
  claudeModel: string;
  claudeCommand: string;
  todoistProjectMap: Record<string, string>;
  extensionInstalled: boolean;
}
```

Add defaults at `settings.ts:29`:

```typescript
const defaults: AppSettings = {
  // ... existing defaults ...
  onboardingComplete: false,
  userName: "",
  claudeModel: "sonnet",
  claudeCommand: "claude",
  todoistProjectMap: {},
  extensionInstalled: false,
};
```

**Step 2: Verify the app still loads**

Run: `npm run dev`
Expected: App loads without errors; new settings default to their values.

**Step 3: Commit**

```bash
git add src/lib/stores/settings.ts
git commit -m "feat: add onboarding, Claude, and extension settings fields"
```

---

### Task 2: Add HuggingFace token to Stronghold credentials

**Files:**
- Modify: `src/lib/stores/credentials.ts:58-74`

The credentials store already has `storeValue`/`getValue` helpers for Stronghold. Add two exported functions for the HF token, following the same pattern.

**Step 1: Add HF token functions**

Add after the `disconnect` function at `credentials.ts:143`:

```typescript
export async function saveHuggingFaceToken(token: string): Promise<void> {
  await storeValue("huggingface.token", token);
}

export async function getHuggingFaceToken(): Promise<string | null> {
  return getValue("huggingface.token");
}
```

**Step 2: Commit**

```bash
git add src/lib/stores/credentials.ts
git commit -m "feat: add Stronghold storage for HuggingFace token"
```

---

### Task 3: Create Onboarding wizard component

**Files:**
- Create: `src/lib/components/Onboarding.svelte`

**Step 1: Create the wizard component**

Four-step wizard with back/next navigation. Uses `$state` for current step and form values. Pre-fills from current settings (for re-run case).

```svelte
<script lang="ts">
  import { get } from "svelte/store";
  import { settings, saveSetting, saveAllSettings } from "../stores/settings";
  import { saveHuggingFaceToken, getHuggingFaceToken } from "../stores/credentials";
  import { open } from "@tauri-apps/plugin-dialog";
  import { checkDriveType } from "../tauri";

  let step = $state(0);
  const totalSteps = 4;

  // Form state — pre-fill from current settings
  let recordingsFolder = $state(get(settings).recordingsFolder);
  let userName = $state(get(settings).userName);
  let vaultPath = $state(get(settings).vaultPath);
  let hfToken = $state("");
  let claudeCommand = $state(get(settings).claudeCommand || "claude");
  let claudeModel = $state(get(settings).claudeModel || "sonnet");
  let driveWarning = $state("");

  // Load existing HF token on mount
  import { onMount } from "svelte";
  onMount(async () => {
    const existing = await getHuggingFaceToken();
    if (existing) hfToken = existing;
  });

  // Validation
  let canAdvance = $derived.by(() => {
    if (step === 1) return recordingsFolder.trim() !== "" && userName.trim() !== "";
    if (step === 2) return vaultPath.trim() !== "";
    if (step === 3) return hfToken.trim() !== "" && claudeCommand.trim() !== "";
    return true;
  });

  async function browseRecordings() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      recordingsFolder = selected as string;
      // Check drive type for SSD warning
      try {
        const driveType = await checkDriveType(recordingsFolder);
        driveWarning = driveType === "HDD"
          ? "Warning: Multi-stream recording needs SSD throughput. This drive appears to be an HDD."
          : "";
      } catch {
        driveWarning = "";
      }
    }
  }

  async function browseVault() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) vaultPath = selected as string;
  }

  async function finish() {
    // Save all settings
    const current = get(settings);
    await saveAllSettings({
      ...current,
      recordingsFolder,
      userName,
      vaultPath,
      claudeCommand,
      claudeModel,
      onboardingComplete: true,
    });
    // Save HF token to Stronghold
    await saveHuggingFaceToken(hfToken);
  }

  function next() {
    if (step < totalSteps - 1 && canAdvance) step++;
  }
  function back() {
    if (step > 0) step--;
  }
</script>

<div
  style="
    height: 100vh;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    background: var(--bg);
    font-family: 'DM Sans', sans-serif;
    color: var(--text);
  "
>
  <div style="width: 100%; max-width: 480px; padding: 0 24px;">

    {#if step === 0}
      <!-- Welcome -->
      <div style="text-align: center;">
        <h1 style="font-family: 'Source Serif 4', serif; font-size: 32px; font-weight: 700; margin-bottom: 8px;">
          Welcome to Recap
        </h1>
        <p style="color: var(--text-muted); font-size: 15px; margin-bottom: 32px;">
          Record meetings, transcribe with AI, and build your knowledge base.
        </p>
        <button
          onclick={() => step = 1}
          style="
            padding: 10px 32px;
            background: var(--gold);
            color: var(--bg);
            border: none;
            border-radius: 8px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
          "
        >
          Get Started
        </button>
      </div>

    {:else if step === 1}
      <!-- Storage -->
      <h2 style="font-family: 'Source Serif 4', serif; font-size: 22px; font-weight: 600; margin-bottom: 4px;">
        Storage
      </h2>
      <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 20px;">
        Where recordings and data are saved.
      </p>

      <div style="display: flex; flex-direction: column; gap: 16px;">
        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
            Recordings Folder
          </span>
          <div style="display: flex; gap: 8px;">
            <input
              type="text"
              bind:value={recordingsFolder}
              placeholder="Select a folder..."
              style="flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
            />
            <button
              onclick={browseRecordings}
              style="background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 14px;"
            >
              Browse
            </button>
          </div>
          {#if driveWarning}
            <p style="color: var(--warning); font-size: 12px; margin-top: 4px;">{driveWarning}</p>
          {/if}
        </label>

        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
            Your Name
          </span>
          <input
            type="text"
            bind:value={userName}
            placeholder="Used to identify your actions in meeting notes"
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
          />
        </label>
      </div>

    {:else if step === 2}
      <!-- Vault -->
      <h2 style="font-family: 'Source Serif 4', serif; font-size: 22px; font-weight: 600; margin-bottom: 4px;">
        Obsidian Vault
      </h2>
      <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 20px;">
        Where meeting notes are written.
      </p>

      <label style="display: block; margin-bottom: 16px;">
        <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
          Vault Path
        </span>
        <div style="display: flex; gap: 8px;">
          <input
            type="text"
            bind:value={vaultPath}
            placeholder="Select your Obsidian vault..."
            style="flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
          />
          <button
            onclick={browseVault}
            style="background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 14px;"
          >
            Browse
          </button>
        </div>
      </label>

      <div style="background: var(--surface); border: 1px solid var(--border); border-radius: 8px; padding: 12px 16px; font-size: 13px; color: var(--text-muted);">
        <p style="margin-bottom: 8px; font-weight: 500; color: var(--text-secondary);">Default subfolders:</p>
        <div style="font-family: 'DM Mono', monospace; font-size: 12px; line-height: 1.6;">
          <div>Work/Meetings/ — meeting notes</div>
          <div>Work/People/ — participant profiles</div>
          <div>Work/Companies/ — company profiles</div>
        </div>
        <p style="margin-top: 8px; font-size: 12px;">Customizable later in Settings.</p>
      </div>

    {:else if step === 3}
      <!-- Pipeline -->
      <h2 style="font-family: 'Source Serif 4', serif; font-size: 22px; font-weight: 600; margin-bottom: 4px;">
        Pipeline
      </h2>
      <p style="color: var(--text-muted); font-size: 13px; margin-bottom: 20px;">
        Configure the AI tools that process recordings.
      </p>

      <div style="display: flex; flex-direction: column; gap: 16px;">
        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
            HuggingFace Token
          </span>
          <input
            type="password"
            bind:value={hfToken}
            placeholder="hf_..."
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
          />
          <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            Required for speaker diarization. Pyannote models are gated on HuggingFace.
            <a href="https://huggingface.co/settings/tokens" target="_blank" style="color: var(--gold);">Get a token</a>
          </p>
        </label>

        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
            Claude CLI Path
          </span>
          <input
            type="text"
            bind:value={claudeCommand}
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
          />
          <p style="font-size: 12px; color: var(--text-muted); margin-top: 4px;">
            Path to the Claude CLI executable. Default "claude" works if it's on PATH.
          </p>
        </label>

        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
            Claude Model
          </span>
          <select
            bind:value={claudeModel}
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 8px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
          >
            <option value="haiku">Haiku (fastest, cheapest)</option>
            <option value="sonnet">Sonnet (balanced)</option>
            <option value="opus">Opus (most capable)</option>
          </select>
        </label>
      </div>
    {/if}

    <!-- Navigation (steps 1-3) -->
    {#if step > 0}
      <div style="display: flex; justify-content: space-between; margin-top: 28px;">
        <button
          onclick={back}
          style="padding: 8px 20px; background: transparent; border: 1px solid var(--border); border-radius: 6px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif; font-size: 14px;"
        >
          Back
        </button>

        {#if step < totalSteps - 1}
          <button
            onclick={next}
            disabled={!canAdvance}
            style="
              padding: 8px 20px;
              background: {canAdvance ? 'var(--gold)' : 'var(--surface)'};
              color: {canAdvance ? 'var(--bg)' : 'var(--text-faint)'};
              border: none;
              border-radius: 6px;
              font-size: 14px;
              font-weight: 600;
              cursor: {canAdvance ? 'pointer' : 'default'};
              font-family: 'DM Sans', sans-serif;
            "
          >
            Next
          </button>
        {:else}
          <button
            onclick={finish}
            disabled={!canAdvance}
            style="
              padding: 8px 20px;
              background: {canAdvance ? 'var(--gold)' : 'var(--surface)'};
              color: {canAdvance ? 'var(--bg)' : 'var(--text-faint)'};
              border: none;
              border-radius: 6px;
              font-size: 14px;
              font-weight: 600;
              cursor: {canAdvance ? 'pointer' : 'default'};
              font-family: 'DM Sans', sans-serif;
            "
          >
            Finish
          </button>
        {/if}
      </div>

      <!-- Step indicators -->
      <div style="display: flex; justify-content: center; gap: 8px; margin-top: 20px;">
        {#each [1, 2, 3] as s}
          <div
            style="
              width: 8px;
              height: 8px;
              border-radius: 50%;
              background: {step === s ? 'var(--gold)' : 'var(--border)'};
            "
          ></div>
        {/each}
      </div>
    {/if}

  </div>
</div>
```

Note: `checkDriveType` is a new IPC command that needs to be added in Task 6 (Rust backend). If it doesn't exist yet, the SSD warning will silently fail via the catch block.

**Step 2: Verify it renders**

Run: `npm run dev`
Temporarily set `onboardingComplete` default to `false` (already the default) and verify wizard appears.

**Step 3: Commit**

```bash
git add src/lib/components/Onboarding.svelte
git commit -m "feat: create onboarding wizard component (4-step flow)"
```

---

### Task 4: Wire onboarding into App.svelte

**Files:**
- Modify: `src/App.svelte:1-229`

**Step 1: Import Onboarding and gate on `onboardingComplete`**

Add import at `App.svelte:6`:

```typescript
import Onboarding from "./lib/components/Onboarding.svelte";
```

Replace the `{:else}` block at `App.svelte:150` that shows the nav + routes. Wrap it with an onboarding check:

```svelte
  {:else}
    {#if !$settings.onboardingComplete}
      <Onboarding />
    {:else}
      <!-- Nav bar -->
      <nav ...>
        ...existing nav...
      </nav>

      <!-- Route content -->
      <div class="flex-1 overflow-hidden">
        ...existing routes...
      </div>
    {/if}
  {/if}
```

**Step 2: Verify routing works**

- With `onboardingComplete: false` → wizard shows, no nav bar
- Complete wizard → dashboard appears with nav bar
- Refresh → dashboard persists (onboardingComplete saved)

**Step 3: Commit**

```bash
git add src/App.svelte
git commit -m "feat: gate app behind onboarding wizard"
```

---

### Task 5: Create SetupChecklist component

**Files:**
- Create: `src/lib/components/SetupChecklist.svelte`

**Step 1: Create the checklist component**

```svelte
<script lang="ts">
  import { credentials } from "../stores/credentials";
  import { settings, saveSetting } from "../stores/settings";
  import type { ProviderName } from "../stores/credentials";
  import Modal from "./Modal.svelte";
  import ProviderCard from "./ProviderCard.svelte";

  let dismissed = $state(false);
  let activeModal = $state<ProviderName | null>(null);

  type ChecklistItem = {
    id: string;
    label: string;
    provider?: ProviderName;
    done: boolean;
  };

  let items = $derived.by((): ChecklistItem[] => {
    const creds = $credentials;
    const s = $settings;
    return [
      { id: "zoom", label: "Connect Zoom", provider: "zoom", done: creds.zoom.status === "connected" },
      { id: "google", label: "Connect Google", provider: "google", done: creds.google.status === "connected" },
      { id: "microsoft", label: "Connect Microsoft Teams", provider: "microsoft", done: creds.microsoft.status === "connected" },
      { id: "zoho", label: "Connect Zoho", provider: "zoho", done: creds.zoho.status === "connected" },
      { id: "todoist", label: "Connect Todoist", provider: "todoist", done: creds.todoist.status === "connected" },
      { id: "extension", label: "Install browser extension", done: s.extensionInstalled },
    ];
  });

  let allDone = $derived(items.every((i) => i.done));
  let remaining = $derived(items.filter((i) => !i.done));

  let visible = $derived(!dismissed && !allDone && $settings.onboardingComplete);

  function openProvider(provider: ProviderName) {
    activeModal = provider;
  }

  async function markExtensionInstalled() {
    await saveSetting("extensionInstalled", true);
  }

  const providerLabels: Record<string, string> = {
    zoom: "Zoom",
    google: "Google",
    microsoft: "Microsoft Teams",
    zoho: "Zoho",
    todoist: "Todoist",
  };
</script>

{#if visible}
  <div
    style="
      margin: 12px 0;
      padding: 16px 20px;
      background: var(--surface);
      border: 1px solid var(--border);
      border-radius: 10px;
      font-family: 'DM Sans', sans-serif;
    "
  >
    <div style="display: flex; justify-content: space-between; align-items: center; margin-bottom: 12px;">
      <h3 style="font-size: 14px; font-weight: 600; color: var(--text); margin: 0;">
        Finish setting up Recap
      </h3>
      <button
        onclick={() => dismissed = true}
        style="background: none; border: none; color: var(--text-faint); cursor: pointer; font-size: 16px; padding: 0 4px;"
        title="Dismiss for this session"
      >&times;</button>
    </div>

    <div style="display: flex; flex-direction: column; gap: 6px;">
      {#each items as item}
        <div
          style="
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 6px 0;
            {item.id !== items[items.length - 1].id ? 'border-bottom: 1px solid rgba(88,86,80,0.15);' : ''}
          "
        >
          <div style="display: flex; align-items: center; gap: 8px;">
            <span style="color: {item.done ? 'var(--gold)' : 'var(--text-faint)'}; font-size: 14px;">
              {item.done ? '\u2713' : '\u25CB'}
            </span>
            <span style="font-size: 13px; color: {item.done ? 'var(--text-muted)' : 'var(--text)'}; {item.done ? 'text-decoration: line-through;' : ''}">
              {item.label}
            </span>
          </div>

          {#if !item.done}
            {#if item.provider}
              <button
                onclick={() => openProvider(item.provider!)}
                style="
                  padding: 3px 10px;
                  background: rgba(168,160,120,0.1);
                  border: 1px solid rgba(168,160,120,0.2);
                  border-radius: 4px;
                  color: var(--gold);
                  font-size: 12px;
                  cursor: pointer;
                  font-family: 'DM Sans', sans-serif;
                "
              >
                Connect
              </button>
            {:else if item.id === "extension"}
              <button
                onclick={markExtensionInstalled}
                style="
                  padding: 3px 10px;
                  background: rgba(168,160,120,0.1);
                  border: 1px solid rgba(168,160,120,0.2);
                  border-radius: 4px;
                  color: var(--gold);
                  font-size: 12px;
                  cursor: pointer;
                  font-family: 'DM Sans', sans-serif;
                "
              >
                Done
              </button>
            {/if}
          {/if}
        </div>
      {/each}
    </div>
  </div>
{/if}

{#if activeModal}
  <Modal title="{providerLabels[activeModal] ?? activeModal} Connection" onclose={() => activeModal = null}>
    <ProviderCard
      provider={activeModal}
      label={providerLabels[activeModal] ?? activeModal}
      providerState={$credentials[activeModal]}
      showRegion={activeModal === "zoho"}
    />
  </Modal>
{/if}
```

**Step 2: Add to Dashboard**

In `src/routes/Dashboard.svelte`, import and render the checklist above the meeting list. Add import:

```typescript
import SetupChecklist from "../lib/components/SetupChecklist.svelte";
```

Render `<SetupChecklist />` in the dashboard layout between the search bar and meeting list.

**Step 3: Verify checklist behavior**

- Shows after onboarding completion with unconfigured providers
- Clicking "Connect" opens provider modal
- Clicking X dismisses for session
- Refreshing brings it back

**Step 4: Commit**

```bash
git add src/lib/components/SetupChecklist.svelte src/routes/Dashboard.svelte
git commit -m "feat: add inline setup checklist to dashboard"
```

---

### Task 6: Add Rust config.yaml generator + drive type check

**Files:**
- Create: `src-tauri/src/config_gen.rs`
- Modify: `src-tauri/src/lib.rs` (register module + IPC commands)
- Modify: `src-tauri/Cargo.toml` (add serde_yaml if not present)

**Step 1: Check if serde_yaml is available**

Run: `grep serde_yaml src-tauri/Cargo.toml`
If not present, add it.

**Step 2: Create config_gen.rs**

```rust
use serde::Serialize;
use std::collections::HashMap;
use std::path::PathBuf;

#[derive(Serialize)]
struct PipelineConfig {
    vault_path: String,
    recordings_path: String,
    frames_path: String,
    user_name: String,
    whisperx: WhisperXConfig,
    claude: ClaudeConfig,
    todoist: TodoistConfig,
}

#[derive(Serialize)]
struct WhisperXConfig {
    model: String,
    device: String,
    compute_type: String,
    language: String,
}

#[derive(Serialize)]
struct ClaudeConfig {
    command: String,
    model: String,
}

#[derive(Serialize)]
struct TodoistConfig {
    default_project: String,
    labels: String,
    project_map: HashMap<String, String>,
}

/// Generate config.yaml from Tauri settings store.
/// Writes to {recordings_path}/config.yaml.
/// Returns the path to the generated config file.
#[tauri::command]
pub async fn generate_pipeline_config(
    app: tauri::AppHandle,
    recordings_path: String,
) -> Result<String, String> {
    use tauri_plugin_store::StoreExt;

    let store = app.store("settings.json")
        .map_err(|e| format!("Failed to load settings store: {}", e))?;

    let get_str = |key: &str, default: &str| -> String {
        store.get(key)
            .and_then(|v| v.as_str().map(|s| s.to_string()))
            .unwrap_or_else(|| default.to_string())
    };

    let config = PipelineConfig {
        vault_path: get_str("vaultPath", ""),
        recordings_path: recordings_path.clone(),
        frames_path: format!("{}/frames", recordings_path),
        user_name: get_str("userName", ""),
        whisperx: WhisperXConfig {
            model: get_str("whisperxModel", "large-v3"),
            device: get_str("whisperxDevice", "cuda"),
            compute_type: get_str("whisperxComputeType", "float16"),
            language: get_str("whisperxLanguage", "en"),
        },
        claude: ClaudeConfig {
            command: get_str("claudeCommand", "claude"),
            model: get_str("claudeModel", "sonnet"),
        },
        todoist: TodoistConfig {
            default_project: get_str("todoistProject", ""),
            labels: get_str("todoistLabels", ""),
            project_map: store.get("todoistProjectMap")
                .and_then(|v| serde_json::from_value(v.clone()).ok())
                .unwrap_or_default(),
        },
    };

    let yaml = serde_yaml::to_string(&config)
        .map_err(|e| format!("Failed to serialize config: {}", e))?;

    let config_path = PathBuf::from(&recordings_path).join("config.yaml");
    std::fs::write(&config_path, &yaml)
        .map_err(|e| format!("Failed to write config.yaml: {}", e))?;

    Ok(config_path.to_string_lossy().to_string())
}

/// Check if a path is on an HDD or SSD.
/// Returns "SSD", "HDD", or "Unknown".
#[tauri::command]
pub async fn check_drive_type(path: String) -> Result<String, String> {
    // Use Windows WMI or PowerShell to check drive type
    let drive_letter = path.chars().next()
        .ok_or_else(|| "Empty path".to_string())?;

    let output = std::process::Command::new("powershell")
        .args([
            "-NoProfile",
            "-Command",
            &format!(
                "Get-PhysicalDisk | Where-Object {{ (Get-Partition -DiskNumber $_.DeviceId -ErrorAction SilentlyContinue | Get-Volume -ErrorAction SilentlyContinue).DriveLetter -eq '{}' }} | Select-Object -ExpandProperty MediaType",
                drive_letter
            ),
        ])
        .output()
        .map_err(|e| format!("Failed to check drive type: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).trim().to_string();
    Ok(match result.as_str() {
        "SSD" => "SSD".to_string(),
        "HDD" => "HDD".to_string(),
        _ => "Unknown".to_string(),
    })
}
```

**Step 3: Register module and commands in lib.rs**

Add `mod config_gen;` and register `config_gen::generate_pipeline_config` and `config_gen::check_drive_type` in the invoke handler.

**Step 4: Add TypeScript wrapper in tauri.ts**

```typescript
export async function generatePipelineConfig(recordingsPath: string): Promise<string> {
  return invoke<string>("generate_pipeline_config", { recordingsPath });
}

export async function checkDriveType(path: string): Promise<string> {
  return invoke<string>("check_drive_type", { path });
}
```

**Step 5: Commit**

```bash
git add src-tauri/src/config_gen.rs src-tauri/src/lib.rs src-tauri/Cargo.toml src/lib/tauri.ts
git commit -m "feat: add Rust config.yaml generator and drive type check"
```

---

### Task 7: Update sidecar launcher to use generated config + env vars

**Files:**
- Modify: `src-tauri/src/sidecar.rs:14-53`
- Modify: `src-tauri/src/recorder/recorder.rs:948-963`

**Step 1: Update sidecar.rs to accept env vars**

Modify `run_pipeline` to generate the config and pass HF/Todoist tokens as env vars:

```rust
#[tauri::command]
pub async fn run_pipeline(
    app: tauri::AppHandle,
    config_path: String,
    recording_path: String,
    metadata_path: Option<String>,
    from_stage: Option<String>,
) -> Result<SidecarResult, String> {
    // Read secrets from Stronghold
    let hf_token = get_stronghold_value(&app, "huggingface.token").await.unwrap_or_default();
    let todoist_token = get_stronghold_value(&app, "todoist.api_token").await.unwrap_or_default();

    let mut args = vec![
        "process".to_string(),
        "--config".to_string(),
        config_path,
        recording_path,
    ];

    if let Some(meta) = metadata_path {
        args.push(meta);
    }

    if let Some(stage) = from_stage {
        args.push("--from".to_string());
        args.push(stage);
    }

    let sidecar = app
        .shell()
        .sidecar("recap-pipeline")
        .map_err(|e| format!("Failed to create sidecar command: {}", e))?
        .args(&args)
        .env("HUGGINGFACE_TOKEN", &hf_token)
        .env("TODOIST_API_TOKEN", &todoist_token);

    let output = sidecar
        .output()
        .await
        .map_err(|e| format!("Sidecar execution failed: {}", e))?;

    Ok(SidecarResult {
        success: output.status.success(),
        stdout: String::from_utf8_lossy(&output.stdout).to_string(),
        stderr: String::from_utf8_lossy(&output.stderr).to_string(),
    })
}
```

Add a helper to read from Stronghold:

```rust
async fn get_stronghold_value(app: &tauri::AppHandle, key: &str) -> Option<String> {
    // Read from the Stronghold vault
    // Implementation depends on how tauri-plugin-stronghold exposes Rust-side reads
    // May need to use the plugin's API directly
    None // Placeholder — implement based on Stronghold plugin API
}
```

**Step 2: Update recorder.rs to generate config before launch**

At `recorder.rs:948`, replace the hardcoded `config.json` path with a call to generate_pipeline_config:

```rust
// Generate config.yaml from settings store
let recordings_path = /* read from settings store */;
let config_path = crate::config_gen::generate_pipeline_config_sync(app.clone(), recordings_path)?;
```

**Step 3: Commit**

```bash
git add src-tauri/src/sidecar.rs src-tauri/src/recorder/recorder.rs
git commit -m "feat: sidecar uses generated config.yaml and env var secrets"
```

---

### Task 8: Update Python pipeline to read env vars

**Files:**
- Modify: `recap/config.py:64-92`
- Modify: `recap/transcribe.py:41-47`
- Modify: `recap/analyze.py:49-53`

**Step 1: Update config.py to support env var overrides**

Add `compute_type` to `WhisperXConfig`, `model` to `ClaudeConfig`, and env var fallbacks:

```python
import os

@dataclass
class WhisperXConfig:
    model: str = "large-v3"
    device: str = "cuda"
    compute_type: str = "float16"
    language: str = "en"

@dataclass
class ClaudeConfig:
    command: str = "claude"
    model: str = "sonnet"
```

In `load_config`, add env var overrides after loading yaml:

```python
def load_config(path: pathlib.Path) -> RecapConfig:
    # ... existing yaml loading ...

    config = RecapConfig(
        # ... existing fields ...
        huggingface_token=os.environ.get("HUGGINGFACE_TOKEN", raw.get("huggingface_token", "")),
        # ...
    )

    # Override todoist token from env
    todoist_token = os.environ.get("TODOIST_API_TOKEN")
    if todoist_token:
        config.todoist.api_token = todoist_token

    return config
```

**Step 2: Update analyze.py to pass --model flag**

In `analyze()`, accept `claude_model` parameter and pass it:

```python
def analyze(
    transcript: TranscriptResult,
    metadata: MeetingMetadata,
    prompt_path: pathlib.Path,
    claude_command: str = "claude",
    claude_model: str = "sonnet",
) -> AnalysisResult:
    # ...
    cmd = [claude_command, "--print", "--output-format", "json"]
    if claude_model:
        cmd.extend(["--model", claude_model])
    result = subprocess.run(cmd, input=prompt, capture_output=True, text=True)
```

**Step 3: Update pipeline.py to pass model through**

At `pipeline.py:270`, pass `claude_model=config.claude.model` to `analyze()`.

**Step 4: Update transcribe.py to use compute_type from config**

The `transcribe` function at `transcribe.py:56` hardcodes `compute_type="float16"`. Add a `compute_type` parameter:

```python
def transcribe(
    audio_path: pathlib.Path,
    model_name: str = "large-v3",
    device: str = "cuda",
    compute_type: str = "float16",
    hf_token: str = "",
    language: str | None = "en",
    save_transcript: pathlib.Path | None = None,
) -> TranscriptResult:
    # ...
    model = whisperx.load_model(
        model_name, device=device, language=language, compute_type=compute_type
    )
```

Update `pipeline.py:204` to pass `compute_type=config.whisperx.compute_type`.

**Step 5: Run tests**

Run: `python -m pytest tests/ -v`
Expected: All existing tests pass.

**Step 6: Commit**

```bash
git add recap/config.py recap/analyze.py recap/transcribe.py recap/pipeline.py
git commit -m "feat: pipeline reads env var secrets and supports Claude model/compute_type config"
```

---

### Task 9: Add Claude and HuggingFace fields to Settings page

**Files:**
- Create: `src/lib/components/ClaudeSettings.svelte`
- Modify: `src/lib/components/WhisperXSettings.svelte`
- Modify: `src/lib/components/TodoistSettings.svelte`
- Modify: `src/lib/components/GeneralSettings.svelte`
- Modify: `src/routes/Settings.svelte`

**Step 1: Create ClaudeSettings component**

```svelte
<script lang="ts">
  import { settings, saveSetting } from "../stores/settings";
</script>

<div style="display:flex;flex-direction:column;gap:12px;">
  <label style="display:block;">
    <span style="display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;">Model</span>
    <select
      value={$settings.claudeModel}
      onchange={async (e) => await saveSetting("claudeModel", e.currentTarget.value)}
      style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;"
    >
      <option value="haiku">Haiku (fastest, cheapest)</option>
      <option value="sonnet">Sonnet (balanced)</option>
      <option value="opus">Opus (most capable)</option>
    </select>
  </label>

  <label style="display:block;">
    <span style="display:block;font-size:14px;color:var(--text-muted);margin-bottom:4px;font-family:'DM Sans',sans-serif;">CLI Path</span>
    <input
      type="text"
      value={$settings.claudeCommand}
      onblur={async (e) => { const v = e.currentTarget.value; if (v !== $settings.claudeCommand) await saveSetting("claudeCommand", v); }}
      style="width:100%;background:var(--surface);border:1px solid var(--border);border-radius:6px;padding:6px 12px;font-size:15px;color:var(--text);font-family:'DM Sans',sans-serif;outline:none;"
      placeholder="claude"
    />
    <span style="font-size:12px;color:var(--text-muted);">Path to Claude CLI executable. Default "claude" if on PATH.</span>
  </label>
</div>
```

**Step 2: Add HF token to WhisperXSettings**

Add a password input that reads/writes via `getHuggingFaceToken`/`saveHuggingFaceToken` from credentials store.

**Step 3: Add project map editor to TodoistSettings**

A simple key-value pair editor: meeting type input + project name input + add/remove buttons. Saves to `todoistProjectMap` setting.

**Step 4: Add "Re-run setup wizard" to GeneralSettings**

```svelte
<button
  onclick={async () => { await saveSetting("onboardingComplete", false); }}
  style="padding:6px 16px;background:var(--surface);border:1px solid var(--border);border-radius:6px;color:var(--text-secondary);cursor:pointer;font-family:'DM Sans',sans-serif;font-size:14px;"
>
  Re-run Setup Wizard
</button>
```

**Step 5: Add Claude section to Settings.svelte**

Add between Recording and WhisperX sections:

```svelte
<SettingsSection title="Claude">
  <ClaudeSettings />
</SettingsSection>
```

**Step 6: Verify all new fields save correctly**

**Step 7: Commit**

```bash
git add src/lib/components/ClaudeSettings.svelte src/lib/components/WhisperXSettings.svelte src/lib/components/TodoistSettings.svelte src/lib/components/GeneralSettings.svelte src/routes/Settings.svelte
git commit -m "feat: add Claude, HF token, project map, and re-run wizard to Settings"
```

---

### Task 10: Actionable pipeline error messages

**Files:**
- Modify: `recap/pipeline.py:154-366`
- Modify: `recap/transcribe.py:41-92`
- Modify: `recap/analyze.py:49-91`
- Create: `recap/errors.py`

**Step 1: Create errors.py with error mapping helper**

```python
"""Actionable error messages for pipeline failures."""
from __future__ import annotations

import errno
import shutil


def map_error(stage: str, error: Exception, **context: str) -> str:
    """Map a raw exception to an actionable error message.

    Returns an actionable string if the error matches a known pattern,
    otherwise returns the raw error string.
    """
    msg = str(error).lower()

    # Cross-stage errors
    if isinstance(error, OSError) and error.errno == errno.ENOSPC:
        return f"Disk full — free space and retry"
    if "recordings" in context and not _path_exists(context.get("recordings", "")):
        return f"Recordings directory not found — update it in Settings > Recording"

    if stage == "transcribe":
        return _map_transcribe_error(error, msg, context)
    elif stage == "analyze":
        return _map_analyze_error(error, msg, context)
    elif stage == "export":
        return _map_export_error(error, msg, context)
    elif stage == "frames":
        return _map_frames_error(error, msg, context)
    elif stage == "todoist":
        return _map_todoist_error(error, msg, context)

    return str(error)


def _path_exists(path: str) -> bool:
    import pathlib
    return pathlib.Path(path).exists() if path else True


def _map_transcribe_error(error: Exception, msg: str, ctx: dict) -> str:
    if "401" in msg or "unauthorized" in msg or "authentication" in msg:
        return "HuggingFace authentication failed — check your token in Settings > WhisperX"
    if "cuda" in msg and ("not available" in msg or "no cuda" in msg):
        return "CUDA not available — check GPU drivers or switch device to 'cpu' in Settings > WhisperX"
    if "out of memory" in msg or "cuda out of memory" in msg:
        return "GPU out of memory — try a smaller model (e.g., 'medium') in Settings > WhisperX"
    if "download" in msg or "connection" in msg or "resolve" in msg:
        return "Failed to download WhisperX model — check your internet connection and HuggingFace token"
    if isinstance(error, (FileNotFoundError, OSError)):
        return "Audio file not found or unreadable — recording may be incomplete"
    return str(error)


def _map_analyze_error(error: Exception, msg: str, ctx: dict) -> str:
    command = ctx.get("command", "claude")
    if isinstance(error, FileNotFoundError) or "not found" in msg or "no such file" in msg:
        if "prompt" in msg or "template" in msg:
            return f"Prompt template not found — check Recap installation"
        return f"Claude CLI not found at '{command}' — update the path in Settings > Claude"
    if "rate" in msg and "limit" in msg:
        return "Claude rate limited — wait a few minutes and retry"
    if isinstance(error, RuntimeError) and "failed after" in msg:
        stderr = ctx.get("last_error", "")
        if "auth" in stderr.lower() or "api key" in stderr.lower():
            return "Claude analysis failed — check Claude CLI is authenticated (run 'claude' in a terminal)"
        return "Claude returned unexpected output — retry (transient) or check prompt template"
    return str(error)


def _map_export_error(error: Exception, msg: str, ctx: dict) -> str:
    vault_path = ctx.get("vault_path", "")
    if isinstance(error, FileNotFoundError) or "not found" in msg:
        return f"Vault path does not exist — update it in Settings > Vault"
    if isinstance(error, PermissionError) or "permission" in msg:
        return f"Cannot write to vault — check folder permissions for {vault_path}"
    return str(error)


def _map_frames_error(error: Exception, msg: str, ctx: dict) -> str:
    if "ffmpeg" in msg or "ffprobe" in msg:
        if "not found" in msg or "no such file" in msg:
            return "ffmpeg not found — ensure ffmpeg is installed and on system PATH"
    if isinstance(error, FileNotFoundError):
        return "Recording file not found — it may have been moved or deleted"
    return str(error)


def _map_todoist_error(error: Exception, msg: str, ctx: dict) -> str:
    if "401" in msg or "unauthorized" in msg or "forbidden" in msg:
        return "Todoist authentication failed — reconnect in Settings > Todoist"
    return str(error)
```

**Step 2: Integrate into pipeline.py**

Replace raw `str(e)` in `_mark_stage` calls with `map_error()`:

At each stage's except block, e.g. transcribe at `pipeline.py:214`:

```python
from recap.errors import map_error

# In transcribe except block:
except Exception as e:
    actionable = map_error("transcribe", e)
    _mark_stage(status, "transcribe", False, actionable)
    _save_status(working_dir, status, recording_dest)
    raise

# In analyze except block:
except Exception as e:
    actionable = map_error("analyze", e, command=config.claude.command, last_error=str(e))
    _mark_stage(status, "analyze", False, actionable)
    _save_status(working_dir, status, recording_dest)
    raise

# In export except block:
except Exception as e:
    actionable = map_error("export", e, vault_path=str(config.vault_path))
    _mark_stage(status, "export", False, actionable)
    _save_status(working_dir, status, recording_dest)
    raise

# In frames except block:
except Exception as e:
    actionable = map_error("frames", e)
    _mark_stage(status, "frames", False, actionable)
    ...
```

**Step 3: Write tests for error mapping**

Create `tests/test_errors.py`:

```python
from recap.errors import map_error

def test_hf_auth_error():
    err = Exception("401 Unauthorized: invalid token")
    result = map_error("transcribe", err)
    assert "HuggingFace authentication" in result
    assert "Settings > WhisperX" in result

def test_cuda_unavailable():
    err = RuntimeError("CUDA not available")
    result = map_error("transcribe", err)
    assert "CUDA not available" in result

def test_gpu_oom():
    err = RuntimeError("CUDA out of memory")
    result = map_error("transcribe", err)
    assert "GPU out of memory" in result
    assert "smaller model" in result

def test_claude_not_found():
    err = FileNotFoundError("No such file: claude")
    result = map_error("analyze", err, command="/usr/bin/claude")
    assert "Claude CLI not found" in result

def test_vault_missing():
    err = FileNotFoundError("Path not found")
    result = map_error("export", err, vault_path="/foo/vault")
    assert "Vault path does not exist" in result

def test_ffmpeg_not_found():
    err = RuntimeError("ffmpeg not found in PATH")
    result = map_error("frames", err)
    assert "ffmpeg not found" in result

def test_todoist_auth():
    err = Exception("401 Unauthorized")
    result = map_error("todoist", err)
    assert "Todoist authentication" in result

def test_unknown_error_passthrough():
    err = ValueError("something unexpected")
    result = map_error("transcribe", err)
    assert result == "something unexpected"

def test_disk_full():
    err = OSError(28, "No space left on device")
    result = map_error("transcribe", err)
    assert "Disk full" in result
```

**Step 4: Run tests**

Run: `python -m pytest tests/test_errors.py -v`
Expected: All tests pass.

**Step 5: Run full test suite**

Run: `python -m pytest tests/ -v`
Expected: All tests pass.

**Step 6: Commit**

```bash
git add recap/errors.py tests/test_errors.py recap/pipeline.py
git commit -m "feat: actionable pipeline error messages with Settings references"
```

---

### Task 11: Update future-phases.md and MANIFEST.md

**Files:**
- Modify: `docs/plans/future-phases.md`
- Modify: `MANIFEST.md`

**Step 1: Mark Phase 7 as complete in future-phases.md**

Change the Phase 7 section to `~~Phase 7: Onboarding Flow~~ (Complete)` with a brief summary.

**Step 2: Regenerate MANIFEST.md**

Update the Structure section to include new files:
- `src/lib/components/Onboarding.svelte`
- `src/lib/components/SetupChecklist.svelte`
- `src/lib/components/ClaudeSettings.svelte`
- `src-tauri/src/config_gen.rs`
- `recap/errors.py`
- `tests/test_errors.py`

Update Key Relationships to note:
- Onboarding gates app behind `onboardingComplete` setting
- config_gen.rs generates config.yaml from settings store before sidecar launch
- sidecar.rs passes HF/Todoist tokens as env vars
- errors.py maps exceptions to actionable messages referencing Settings sections

**Step 3: Commit**

```bash
git add docs/plans/future-phases.md MANIFEST.md
git commit -m "docs: mark Phase 7 complete, update MANIFEST"
```
