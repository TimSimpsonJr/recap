<script lang="ts">
  import { onMount } from "svelte";
  import { get } from "svelte/store";
  import { open } from "@tauri-apps/plugin-dialog";
  import { settings, saveAllSettings } from "../stores/settings";
  import { saveHuggingFaceToken, getHuggingFaceToken } from "../stores/credentials";
  import { checkDriveType } from "../tauri";
  import { openUrl } from "@tauri-apps/plugin-opener";
  import type { AppSettings } from "../stores/settings";

  let step = $state(0);
  let showHfHelp = $state(false);

  // Step 1: Storage
  let recordingsFolder = $state("");
  let userName = $state("");
  let driveWarning = $state("");

  // Step 2: Vault
  let vaultPath = $state("");

  // Step 3: Pipeline
  let hfToken = $state("");
  let claudeCommand = $state("claude");
  let claudeModel = $state("sonnet");

  // Derived: can advance from each step
  let canAdvanceStorage = $derived(recordingsFolder !== "" && userName !== "");
  let canAdvanceVault = $derived(vaultPath !== "");
  let canFinish = $derived(hfToken !== "");

  function handleWindowClick() {
    if (showHfHelp) showHfHelp = false;
  }

  function handlePopoverClick(e: MouseEvent) {
    e.stopPropagation();
    const target = e.target as HTMLElement;
    const anchor = target.closest("a");
    if (anchor?.href) {
      e.preventDefault();
      openUrl(anchor.href);
    }
  }

  onMount(async () => {
    const current = get(settings);
    recordingsFolder = current.recordingsFolder || "";
    userName = current.userName || "";
    vaultPath = current.vaultPath || "";
    claudeCommand = current.claudeCommand || "claude";
    claudeModel = current.claudeModel || "sonnet";

    try {
      const token = await getHuggingFaceToken();
      if (token) hfToken = token;
    } catch {
      // Credentials store may not be ready yet
    }
  });

  async function browseRecordingsFolder() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      recordingsFolder = selected as string;
      driveWarning = "";
      // Fire drive check in background — don't block the UI update
      checkDriveType(recordingsFolder)
        .then((driveType) => {
          if (driveType === "HDD") {
            driveWarning = "This appears to be a hard disk drive. Multi-stream recording requires an SSD for reliable performance.";
          }
        })
        .catch(() => {});
    }
  }

  async function browseVaultPath() {
    const selected = await open({ directory: true, multiple: false });
    if (selected) {
      vaultPath = selected as string;
    }
  }

  async function finish() {
    const current = get(settings);
    const merged: AppSettings = {
      ...current,
      recordingsFolder,
      userName,
      vaultPath,
      claudeCommand,
      claudeModel,
      onboardingComplete: true,
    };
    await saveAllSettings(merged);
    await saveHuggingFaceToken(hfToken);
  }

  function next() {
    if (step < 3) step++;
  }

  function back() {
    if (step > 0) step--;
  }
</script>

<!-- svelte-ignore a11y_click_events_have_key_events -->
<svelte:window onclick={handleWindowClick} />

<div style="
  position: fixed;
  inset: 0;
  background: var(--bg);
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  font-family: 'DM Sans', sans-serif;
  color: var(--text);
  z-index: 9999;
">
  <div style="
    width: 100%;
    max-width: 520px;
    padding: 0 24px;
  ">
    {#if step === 0}
      <!-- Welcome -->
      <div style="text-align: center;">
        <h1 style="
          font-family: 'Source Serif 4', serif;
          font-size: 36px;
          font-weight: 700;
          color: var(--text);
          margin: 0 0 8px 0;
        ">Welcome to Recap</h1>
        <p style="
          font-size: 16px;
          color: var(--text-muted);
          margin: 0 0 32px 0;
        ">Record, transcribe, and analyze your meetings automatically.</p>
        <button
          onclick={next}
          style="
            background: var(--gold);
            color: var(--bg);
            border: none;
            border-radius: 8px;
            padding: 10px 32px;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            font-family: 'DM Sans', sans-serif;
          "
          onmouseenter={(e) => { e.currentTarget.style.background = 'var(--gold-hover)'; }}
          onmouseleave={(e) => { e.currentTarget.style.background = 'var(--gold)'; }}
        >Get Started</button>
      </div>

    {:else if step === 1}
      <!-- Storage -->
      <h2 style="
        font-family: 'Source Serif 4', serif;
        font-size: 24px;
        font-weight: 700;
        color: var(--text);
        margin: 0 0 24px 0;
      ">Storage &amp; Identity</h2>

      <div style="display: flex; flex-direction: column; gap: 16px;">
        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">Recordings Folder</span>
          <div style="display: flex; gap: 8px;">
            <input
              type="text"
              bind:value={recordingsFolder}
              style="flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
              placeholder="Where to save recordings"
            />
            <button
              onclick={browseRecordingsFolder}
              style="font-size: 14.5px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif;"
              onmouseenter={(e) => { e.currentTarget.style.background = 'var(--raised)'; }}
              onmouseleave={(e) => { e.currentTarget.style.background = 'var(--surface)'; }}
            >Browse</button>
          </div>
          {#if driveWarning}
            <p style="font-size: 13px; color: var(--warning); margin: 6px 0 0 0;">{driveWarning}</p>
          {/if}
        </label>

        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">Your Name</span>
          <input
            type="text"
            bind:value={userName}
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none; box-sizing: border-box;"
            placeholder="Used to identify you in transcripts"
          />
        </label>
      </div>

      <div style="display: flex; justify-content: space-between; margin-top: 32px;">
        <button
          onclick={back}
          style="background: none; border: 1px solid var(--border); border-radius: 8px; padding: 8px 24px; font-size: 14px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif;"
          onmouseenter={(e) => { e.currentTarget.style.borderColor = 'var(--border-bright)'; }}
          onmouseleave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
        >Back</button>
        <button
          onclick={next}
          disabled={!canAdvanceStorage}
          style="
            background: {canAdvanceStorage ? 'var(--gold)' : 'var(--border)'};
            color: {canAdvanceStorage ? 'var(--bg)' : 'var(--text-faint)'};
            border: none;
            border-radius: 8px;
            padding: 8px 24px;
            font-size: 14px;
            font-weight: 600;
            cursor: {canAdvanceStorage ? 'pointer' : 'not-allowed'};
            font-family: 'DM Sans', sans-serif;
          "
          onmouseenter={(e) => { if (canAdvanceStorage) e.currentTarget.style.background = 'var(--gold-hover)'; }}
          onmouseleave={(e) => { if (canAdvanceStorage) e.currentTarget.style.background = 'var(--gold)'; }}
        >Next</button>
      </div>

    {:else if step === 2}
      <!-- Vault -->
      <h2 style="
        font-family: 'Source Serif 4', serif;
        font-size: 24px;
        font-weight: 700;
        color: var(--text);
        margin: 0 0 24px 0;
      ">Obsidian Vault</h2>

      <div style="display: flex; flex-direction: column; gap: 16px;">
        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">Vault Path</span>
          <div style="display: flex; gap: 8px;">
            <input
              type="text"
              bind:value={vaultPath}
              style="flex: 1; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none;"
              placeholder="Path to your Obsidian vault"
            />
            <button
              onclick={browseVaultPath}
              style="font-size: 14.5px; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif;"
              onmouseenter={(e) => { e.currentTarget.style.background = 'var(--raised)'; }}
              onmouseleave={(e) => { e.currentTarget.style.background = 'var(--surface)'; }}
            >Browse</button>
          </div>
        </label>

        <div style="
          background: var(--surface);
          border: 1px solid var(--border);
          border-radius: 8px;
          padding: 14px 18px;
        ">
          <span style="display: block; font-size: 13px; color: var(--text-muted); margin-bottom: 8px;">Default subfolder structure:</span>
          <div style="font-size: 14px; color: var(--text-secondary); font-family: 'DM Mono', 'Fira Code', monospace; line-height: 1.7;">
            <div>Work/</div>
            <div style="padding-left: 20px;">Meetings/</div>
            <div style="padding-left: 20px;">People/</div>
            <div style="padding-left: 20px;">Companies/</div>
          </div>
        </div>
      </div>

      <div style="display: flex; justify-content: space-between; margin-top: 32px;">
        <button
          onclick={back}
          style="background: none; border: 1px solid var(--border); border-radius: 8px; padding: 8px 24px; font-size: 14px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif;"
          onmouseenter={(e) => { e.currentTarget.style.borderColor = 'var(--border-bright)'; }}
          onmouseleave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
        >Back</button>
        <button
          onclick={next}
          disabled={!canAdvanceVault}
          style="
            background: {canAdvanceVault ? 'var(--gold)' : 'var(--border)'};
            color: {canAdvanceVault ? 'var(--bg)' : 'var(--text-faint)'};
            border: none;
            border-radius: 8px;
            padding: 8px 24px;
            font-size: 14px;
            font-weight: 600;
            cursor: {canAdvanceVault ? 'pointer' : 'not-allowed'};
            font-family: 'DM Sans', sans-serif;
          "
          onmouseenter={(e) => { if (canAdvanceVault) e.currentTarget.style.background = 'var(--gold-hover)'; }}
          onmouseleave={(e) => { if (canAdvanceVault) e.currentTarget.style.background = 'var(--gold)'; }}
        >Next</button>
      </div>

    {:else if step === 3}
      <!-- Pipeline -->
      <h2 style="
        font-family: 'Source Serif 4', serif;
        font-size: 24px;
        font-weight: 700;
        color: var(--text);
        margin: 0 0 24px 0;
      ">Pipeline Configuration</h2>

      <div style="display: flex; flex-direction: column; gap: 16px;">
        <label style="display: block;">
          <span style="display: flex; align-items: center; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">
            HuggingFace Token
            <!-- svelte-ignore a11y_click_events_have_key_events -->
            <!-- svelte-ignore a11y_no_static_element_interactions -->
            <span
              onclick={(e) => { e.preventDefault(); e.stopPropagation(); showHfHelp = !showHfHelp; }}
              style="
                display: inline-flex;
                align-items: center;
                justify-content: center;
                width: 16px;
                height: 16px;
                margin-left: 6px;
                border-radius: 50%;
                background: var(--border);
                color: var(--text-muted);
                font-size: 11px;
                font-weight: 700;
                cursor: pointer;
                user-select: none;
                flex-shrink: 0;
              "
              title="How to get a HuggingFace token"
            >?</span>
          </span>
          <div style="position: relative;">
            <input
              type="password"
              bind:value={hfToken}
              style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none; box-sizing: border-box;"
              placeholder="hf_..."
            />
            {#if showHfHelp}
              <!-- svelte-ignore a11y_click_events_have_key_events -->
              <!-- svelte-ignore a11y_no_static_element_interactions -->
              <div
                onclick={handlePopoverClick}
                style="
                  position: absolute;
                  top: calc(100% + 8px);
                  left: 0;
                  right: 0;
                  background: var(--raised, var(--surface));
                  border: 1px solid var(--border);
                  border-radius: 8px;
                  padding: 16px 18px;
                  font-size: 13px;
                  color: var(--text-secondary);
                  line-height: 1.6;
                  z-index: 100;
                  box-shadow: 0 8px 24px rgba(0,0,0,0.4);
                "
              >
                <div style="margin-bottom: 10px;">
                  <span style="font-weight: 600; color: var(--text); font-size: 14px;">Setup Guide</span>
                </div>
                <p style="margin: 0 0 6px 0; font-weight: 600; color: var(--text);">1. Create a token</p>
                <ol style="margin: 0 0 12px 0; padding-left: 20px;">
                  <li>Go to <a href="https://huggingface.co/settings/tokens" target="_blank" rel="noopener noreferrer" style="color: var(--blue);">huggingface.co/settings/tokens</a></li>
                  <li>Click "Create new token"</li>
                  <li>Name it "Recap", select <strong>Read</strong> access</li>
                  <li>Copy the token (starts with <code style="background: var(--bg); padding: 1px 4px; border-radius: 3px;">hf_...</code>)</li>
                </ol>
                <p style="margin: 0 0 6px 0; font-weight: 600; color: var(--text);">2. Accept model licenses</p>
                <p style="margin: 0 0 6px 0;">Speaker diarization requires accepting these free licenses:</p>
                <ol style="margin: 0; padding-left: 20px;">
                  <li><a href="https://huggingface.co/pyannote/segmentation-3.0" target="_blank" rel="noopener noreferrer" style="color: var(--blue);">pyannote/segmentation-3.0</a> — click "Agree and access"</li>
                  <li><a href="https://huggingface.co/pyannote/speaker-diarization-3.1" target="_blank" rel="noopener noreferrer" style="color: var(--blue);">pyannote/speaker-diarization-3.1</a> — click "Agree and access"</li>
                </ol>
              </div>
            {/if}
          </div>
        </label>

        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">Claude CLI Path</span>
          <input
            type="text"
            bind:value={claudeCommand}
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none; box-sizing: border-box;"
            placeholder="claude"
          />
        </label>

        <label style="display: block;">
          <span style="display: block; font-size: 14px; color: var(--text-muted); margin-bottom: 4px;">Claude Model</span>
          <select
            bind:value={claudeModel}
            style="width: 100%; background: var(--surface); border: 1px solid var(--border); border-radius: 6px; padding: 6px 12px; font-size: 15px; color: var(--text); font-family: 'DM Sans', sans-serif; outline: none; box-sizing: border-box;"
          >
            <option value="haiku">Haiku</option>
            <option value="sonnet">Sonnet</option>
            <option value="opus">Opus</option>
          </select>
        </label>
      </div>

      <div style="display: flex; justify-content: space-between; margin-top: 32px;">
        <button
          onclick={back}
          style="background: none; border: 1px solid var(--border); border-radius: 8px; padding: 8px 24px; font-size: 14px; color: var(--text-secondary); cursor: pointer; font-family: 'DM Sans', sans-serif;"
          onmouseenter={(e) => { e.currentTarget.style.borderColor = 'var(--border-bright)'; }}
          onmouseleave={(e) => { e.currentTarget.style.borderColor = 'var(--border)'; }}
        >Back</button>
        <button
          onclick={finish}
          disabled={!canFinish}
          style="
            background: {canFinish ? 'var(--gold)' : 'var(--border)'};
            color: {canFinish ? 'var(--bg)' : 'var(--text-faint)'};
            border: none;
            border-radius: 8px;
            padding: 8px 24px;
            font-size: 14px;
            font-weight: 600;
            cursor: {canFinish ? 'pointer' : 'not-allowed'};
            font-family: 'DM Sans', sans-serif;
          "
          onmouseenter={(e) => { if (canFinish) e.currentTarget.style.background = 'var(--gold-hover)'; }}
          onmouseleave={(e) => { if (canFinish) e.currentTarget.style.background = 'var(--gold)'; }}
        >Finish</button>
      </div>
    {/if}
  </div>

  <!-- Step indicators (dots for steps 1-3, not shown on welcome) -->
  {#if step > 0}
    <div style="
      display: flex;
      gap: 8px;
      margin-top: 40px;
    ">
      {#each [1, 2, 3] as dotStep}
        <div style="
          width: 8px;
          height: 8px;
          border-radius: 50%;
          background: {step === dotStep ? 'var(--gold)' : 'var(--border)'};
          transition: background 0.2s;
        "></div>
      {/each}
    </div>
  {/if}
</div>
