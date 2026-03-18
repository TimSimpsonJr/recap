# Generation 002: Add Claude CLI constraint

**Date**: 2026-03-18
**Trigger**: /cortex-update

## Changes
- Added constraint to `constraints.md`: **Claude CLI for LLM calls** — all LLM interactions use the `claude` CLI (`claude --print`), not the Anthropic API SDK. Keeps auth/config centralized and avoids managing API keys in the app.

## Rationale
The pipeline already uses `claude --print` for meeting analysis. As we add briefing generation in Phase 5c, this constraint ensures consistency and prevents accidentally introducing direct API SDK usage.
