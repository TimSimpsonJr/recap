use std::path::{Path, PathBuf};
use std::process::Command;

use chrono::{DateTime, Duration, Utc};
use serde::{Deserialize, Serialize};
use tauri::Manager;

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Briefing {
    pub topics: Vec<String>,
    pub action_items: Vec<BriefingActionItem>,
    pub context: String,
    pub relationship_summary: String,
    pub first_meeting: bool,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct BriefingActionItem {
    pub assignee: String,
    pub description: String,
    pub from_meeting: String,
}

/// Wrapper for cached briefing data, storing participants for structured invalidation.
#[derive(Debug, Clone, Serialize, Deserialize)]
struct CachedBriefing {
    participants: Vec<String>,
    briefing: Briefing,
    generated_at: String,
}

// ---------------------------------------------------------------------------
// Cache helpers
// ---------------------------------------------------------------------------

fn cache_dir(app: &tauri::AppHandle) -> PathBuf {
    app.path()
        .app_data_dir()
        .expect("could not resolve app data dir")
        .join("briefing_cache")
}

fn cache_path_for(app: &tauri::AppHandle, event_id: &str) -> PathBuf {
    let safe_id: String = event_id.chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '_' })
        .collect();
    cache_dir(app).join(format!("{}.json", safe_id))
}

fn read_cached_briefing(path: &Path) -> Option<Briefing> {
    let content = std::fs::read_to_string(path).ok()?;
    // Try new CachedBriefing format first, fall back to bare Briefing for old cache files
    if let Ok(cached) = serde_json::from_str::<CachedBriefing>(&content) {
        return Some(cached.briefing);
    }
    serde_json::from_str(&content).ok()
}

fn write_cached_briefing(path: &Path, briefing: &Briefing, participants: &[String]) -> Result<(), String> {
    if let Some(parent) = path.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create briefing cache directory: {}", e))?;
    }
    let cached = CachedBriefing {
        participants: participants.to_vec(),
        briefing: briefing.clone(),
        generated_at: Utc::now().to_rfc3339(),
    };
    let json = serde_json::to_string_pretty(&cached)
        .map_err(|e| format!("Failed to serialize briefing: {}", e))?;
    std::fs::write(path, json)
        .map_err(|e| format!("Failed to write briefing cache: {}", e))?;
    Ok(())
}

// ---------------------------------------------------------------------------
// Past meeting lookup
// ---------------------------------------------------------------------------

/// Find past meeting notes that match the given participants.
///
/// Searches the recordings directory for .meeting.json files and the vault
/// meetings directory for .md files. Returns the content of matched notes.
fn find_past_meeting_notes(
    participants: &[String],
    recordings_dir: &str,
    vault_meetings_dir: Option<&str>,
) -> Vec<(String, String)> {
    let mut notes: Vec<(String, String)> = Vec::new();
    let lookback = Utc::now() - Duration::days(90);

    // Normalize participant names to lowercase for matching
    let participant_lower: Vec<String> = participants
        .iter()
        .map(|p| p.to_lowercase())
        .collect();

    // Scan recordings directory for .meeting.json files
    let recordings_path = PathBuf::from(recordings_dir);
    if recordings_path.is_dir() {
        if let Ok(entries) = std::fs::read_dir(&recordings_path) {
            let mut matched: Vec<(String, String, DateTime<Utc>)> = Vec::new();

            for entry in entries.flatten() {
                let path = entry.path();
                let is_meeting_json = path
                    .file_name()
                    .and_then(|n| n.to_str())
                    .map(|n| n.ends_with(".meeting.json"))
                    .unwrap_or(false);
                if !is_meeting_json {
                    continue;
                }

                let content = match std::fs::read_to_string(&path) {
                    Ok(c) => c,
                    Err(_) => continue,
                };
                let meta: serde_json::Value = match serde_json::from_str(&content) {
                    Ok(m) => m,
                    Err(_) => continue,
                };

                // Check date is within lookback
                let date_str = meta
                    .get("date")
                    .and_then(|v| v.as_str())
                    .unwrap_or("");
                let meeting_date = if let Ok(dt) = DateTime::parse_from_rfc3339(date_str) {
                    dt.with_timezone(&Utc)
                } else {
                    continue;
                };
                if meeting_date < lookback {
                    continue;
                }

                // Check participant overlap
                let meeting_participants: Vec<String> = meta
                    .get("participants")
                    .and_then(|v| v.as_array())
                    .map(|arr| {
                        arr.iter()
                            .filter_map(|v| v.as_str())
                            .map(|s| s.to_lowercase())
                            .collect()
                    })
                    .unwrap_or_default();

                let has_overlap = participant_lower
                    .iter()
                    .any(|p| meeting_participants.iter().any(|mp| mp.contains(p.as_str()) || p.contains(mp.as_str())));

                if !has_overlap {
                    // Also check company name overlap
                    let company = meta
                        .get("company")
                        .and_then(|v| v.as_str())
                        .unwrap_or("")
                        .to_lowercase();
                    if company.is_empty() || !participant_lower.iter().any(|p| p.contains(&company)) {
                        continue;
                    }
                }

                let title = meta
                    .get("title")
                    .and_then(|v| v.as_str())
                    .unwrap_or("Untitled")
                    .to_string();

                matched.push((title, path.display().to_string(), meeting_date));
            }

            // Sort by date descending and take last 4
            matched.sort_by(|a, b| b.2.cmp(&a.2));
            matched.truncate(4);

            // For each matched meeting, try to find its note
            for (title, json_path, _) in &matched {
                // Look for a corresponding note file
                let note_path = json_path.replace(".meeting.json", ".md");
                if let Ok(content) = std::fs::read_to_string(&note_path) {
                    notes.push((title.clone(), content));
                }
            }
        }
    }

    // Also scan vault meetings directory
    if let Some(vault_dir) = vault_meetings_dir {
        let vault_path = PathBuf::from(vault_dir);
        if vault_path.is_dir() {
            if let Ok(entries) = std::fs::read_dir(&vault_path) {
                for entry in entries.flatten() {
                    let path = entry.path();
                    if path.extension().and_then(|e| e.to_str()) != Some("md") {
                        continue;
                    }

                    let content = match std::fs::read_to_string(&path) {
                        Ok(c) => c,
                        Err(_) => continue,
                    };

                    // Check if any participant name appears in the note content
                    let content_lower = content.to_lowercase();
                    let has_match = participant_lower
                        .iter()
                        .any(|p| content_lower.contains(p.as_str()));

                    if has_match {
                        let title = path
                            .file_stem()
                            .and_then(|s| s.to_str())
                            .unwrap_or("Untitled")
                            .to_string();

                        // Avoid duplicates
                        if !notes.iter().any(|(t, _)| t == &title) {
                            notes.push((title, content));
                        }
                    }
                }
            }

            // Cap total notes at 4
            notes.truncate(4);
        }
    }

    notes
}

// ---------------------------------------------------------------------------
// Claude CLI invocation
// ---------------------------------------------------------------------------

fn build_prompt(
    template: &str,
    title: &str,
    participants: &[String],
    time: &str,
    past_notes: &[(String, String)],
    event_description: Option<&str>,
) -> String {
    let participants_text = participants.join(", ");

    let past_notes_text = if past_notes.is_empty() {
        "No past meeting notes found for these participants.".to_string()
    } else {
        past_notes
            .iter()
            .map(|(title, content)| format!("### {}\n\n{}", title, content))
            .collect::<Vec<_>>()
            .join("\n\n---\n\n")
    };

    let mut prompt = template.replace("{{title}}", title);
    prompt = prompt.replace("{{participants}}", &participants_text);
    prompt = prompt.replace("{{time}}", time);
    prompt = prompt.replace("{{past_notes}}", &past_notes_text);

    if let Some(desc) = event_description {
        prompt.push_str(&format!("\n\n## Event Description\n\n{}", desc));
    }

    prompt
}

/// Resolve the Claude CLI executable path.
///
/// 1. If the user configured a custom path in settings, use that.
/// 2. Try bare "claude" (works if it's on the system PATH).
/// 3. Look for Claude Code Desktop at %APPDATA%/Claude/claude-code/<version>/claude.exe
fn resolve_claude_command(configured: &str) -> String {
    // If user set an explicit absolute path, trust it
    if configured != "claude" {
        return configured.to_string();
    }

    // Check if bare "claude" is on PATH
    if Command::new("claude")
        .arg("--version")
        .stdout(std::process::Stdio::null())
        .stderr(std::process::Stdio::null())
        .spawn()
        .is_ok()
    {
        return "claude".to_string();
    }

    // Look for Claude Code Desktop installation
    if let Some(appdata) = std::env::var_os("APPDATA") {
        let claude_code_dir = PathBuf::from(appdata).join("Claude").join("claude-code");
        if claude_code_dir.is_dir() {
            // Find the latest version directory containing claude.exe
            if let Ok(entries) = std::fs::read_dir(&claude_code_dir) {
                let mut versions: Vec<PathBuf> = entries
                    .flatten()
                    .filter(|e| e.path().join("claude.exe").exists())
                    .map(|e| e.path())
                    .collect();
                // Sort by name descending to pick latest version
                versions.sort();
                if let Some(latest) = versions.last() {
                    return latest.join("claude.exe").display().to_string();
                }
            }
        }
    }

    configured.to_string()
}

fn call_claude(prompt: &str, claude_command: &str) -> Result<Briefing, String> {
    use std::io::{Read, Write};
    use std::time::{Duration, Instant};

    let resolved = resolve_claude_command(claude_command);
    let mut child = Command::new(&resolved)
        .args(["--print", "--output-format", "json"])
        .stdin(std::process::Stdio::piped())
        .stdout(std::process::Stdio::piped())
        .stderr(std::process::Stdio::piped())
        .spawn()
        .map_err(|e| format!("Failed to run claude CLI: {}", e))?;

    // Write prompt to stdin and close it
    if let Some(ref mut stdin) = child.stdin {
        stdin.write_all(prompt.as_bytes()).ok();
    }
    // Drop stdin so the child process sees EOF
    child.stdin.take();

    // Poll for completion with a 120-second timeout
    let timeout = Duration::from_secs(120);
    let start = Instant::now();

    let status = loop {
        match child.try_wait() {
            Ok(Some(status)) => break status,
            Ok(None) => {
                if start.elapsed() > timeout {
                    child.kill().ok();
                    return Err("Claude CLI timed out after 120 seconds".to_string());
                }
                std::thread::sleep(Duration::from_millis(100));
            }
            Err(e) => return Err(format!("Failed to wait for Claude CLI: {}", e)),
        }
    };

    // Read stdout and stderr from the finished process
    let mut stdout_buf = String::new();
    let mut stderr_buf = String::new();
    if let Some(ref mut out) = child.stdout {
        out.read_to_string(&mut stdout_buf).ok();
    }
    if let Some(ref mut err) = child.stderr {
        err.read_to_string(&mut stderr_buf).ok();
    }

    if !status.success() {
        // Try to extract a human-readable message from JSON stdout
        let detail = if !stdout_buf.trim().is_empty() {
            if let Ok(v) = serde_json::from_str::<serde_json::Value>(stdout_buf.trim()) {
                v.get("result").and_then(|r| r.as_str()).unwrap_or(stdout_buf.trim()).to_string()
            } else {
                stdout_buf.trim().to_string()
            }
        } else if !stderr_buf.trim().is_empty() {
            stderr_buf.trim().to_string()
        } else {
            format!("exit code {:?}", status.code())
        };
        return Err(detail);
    }

    let stdout = std::borrow::Cow::Borrowed(stdout_buf.as_str());

    // The --output-format json wraps the response; extract the text content
    let output: serde_json::Value = serde_json::from_str(&stdout)
        .map_err(|e| format!("Failed to parse Claude CLI JSON wrapper: {}", e))?;

    // Claude CLI --output-format json returns { "result": "..." } or similar
    // Try to get the text content from the response
    let text = if let Some(result_str) = output.get("result").and_then(|v| v.as_str()) {
        result_str.to_string()
    } else if let Some(text_str) = output.get("text").and_then(|v| v.as_str()) {
        text_str.to_string()
    } else {
        // Maybe the whole output is the JSON briefing directly
        stdout.to_string()
    };

    // Strip markdown code fences if present
    let cleaned = text.trim();
    let json_str = if let Some(start) = cleaned.find("```") {
        let after_fence = &cleaned[start + 3..];
        let content_start = after_fence.find('\n').map(|i| i + 1).unwrap_or(0);
        let rest = &after_fence[content_start..];
        if let Some(end) = rest.find("```") {
            &rest[..end]
        } else {
            rest
        }
    } else {
        cleaned
    };

    serde_json::from_str(json_str.trim())
        .map_err(|e| format!("Failed to parse briefing JSON: {}. Raw: {}", e, &json_str[..json_str.len().min(500)]))
}

// ---------------------------------------------------------------------------
// Tauri commands
// ---------------------------------------------------------------------------

#[tauri::command]
pub async fn generate_briefing(
    app: tauri::AppHandle,
    event_id: String,
    title: String,
    participants: Vec<String>,
    time: String,
    recordings_dir: String,
    vault_meetings_dir: Option<String>,
    event_description: Option<String>,
) -> Result<Briefing, String> {
    // Check cache first
    let cp = cache_path_for(&app, &event_id);
    if let Some(cached) = read_cached_briefing(&cp) {
        return Ok(cached);
    }

    // Find past meeting notes
    let past_notes = find_past_meeting_notes(
        &participants,
        &recordings_dir,
        vault_meetings_dir.as_deref(),
    );

    // Load prompt template
    let prompt_template_path = app
        .path()
        .resource_dir()
        .map_err(|e| format!("Could not resolve resource dir: {}", e))?
        .join("prompts")
        .join("meeting_briefing.md");

    let template = if prompt_template_path.exists() {
        std::fs::read_to_string(&prompt_template_path)
            .map_err(|e| format!("Failed to read prompt template: {}", e))?
    } else {
        // Fallback: try relative to executable
        let exe_dir = std::env::current_exe()
            .map_err(|e| format!("Could not resolve exe dir: {}", e))?
            .parent()
            .map(|p| p.to_path_buf())
            .unwrap_or_default();
        let fallback_path = exe_dir.join("prompts").join("meeting_briefing.md");
        if fallback_path.exists() {
            std::fs::read_to_string(&fallback_path)
                .map_err(|e| format!("Failed to read prompt template: {}", e))?
        } else {
            // Use inline fallback template
            include_str!("../../prompts/meeting_briefing.md").to_string()
        }
    };

    // Read claudeCommand from settings store (default to "claude")
    let claude_command = app
        .path()
        .app_data_dir()
        .ok()
        .and_then(|dir| std::fs::read_to_string(dir.join("settings.json")).ok())
        .and_then(|content| serde_json::from_str::<serde_json::Value>(&content).ok())
        .and_then(|v| v.get("claudeCommand")?.as_str().map(|s| s.to_string()))
        .unwrap_or_else(|| "claude".to_string());

    // Build prompt and call Claude
    let prompt = build_prompt(
        &template,
        &title,
        &participants,
        &time,
        &past_notes,
        event_description.as_deref(),
    );

    let briefing = tokio::task::spawn_blocking(move || call_claude(&prompt, &claude_command))
        .await
        .map_err(|e| format!("Briefing generation task failed: {}", e))?
        .map_err(|e| format!("Briefing generation failed: {}", e))?;

    // Cache the result with participant metadata for structured invalidation
    write_cached_briefing(&cp, &briefing, &participants)?;

    Ok(briefing)
}

// TODO: Add test for briefing cache invalidation — verify that invalidating
// by participant name removes the correct cached files and leaves others intact.
#[tauri::command]
pub async fn invalidate_briefing_cache(
    app: tauri::AppHandle,
    participant_names: Vec<String>,
) -> Result<(), String> {
    let dir = cache_dir(&app);
    if !dir.is_dir() {
        return Ok(());
    }

    let participant_lower: Vec<String> = participant_names
        .iter()
        .map(|p| p.to_lowercase())
        .collect();

    let entries = std::fs::read_dir(&dir)
        .map_err(|e| format!("Failed to read briefing cache directory: {}", e))?;

    for entry in entries.flatten() {
        let path = entry.path();
        if path.extension().and_then(|e| e.to_str()) != Some("json") {
            continue;
        }

        // Deserialize cached briefing and check participant array for overlap
        if let Ok(content) = std::fs::read_to_string(&path) {
            let has_overlap = if let Ok(cached) = serde_json::from_str::<CachedBriefing>(&content) {
                // Structured match against the stored participants list
                let cached_lower: Vec<String> = cached.participants.iter().map(|p| p.to_lowercase()).collect();
                participant_lower.iter().any(|p| {
                    cached_lower.iter().any(|cp| cp.contains(p.as_str()) || p.contains(cp.as_str()))
                })
            } else {
                // Legacy cache format without participants — fall back to text search
                let content_lower = content.to_lowercase();
                participant_lower.iter().any(|p| content_lower.contains(p.as_str()))
            };

            if has_overlap {
                let _ = std::fs::remove_file(&path);
            }
        }
    }

    Ok(())
}
