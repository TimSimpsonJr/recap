---
name: cortex-crusade-report
enabled: false
event: bash
action: warn
conditions:
  - field: command
    operator: regex_match
    pattern: (crusade|church.*agent)
---

**Crusade agent detected.** Consider using report-only mode first to review findings against the project genome before auto-fixing. Crusade agents may not have full architectural context.

Enable this rule with hookify when running crusades: edit `.claude/hookify.cortex-crusade.local.md` and set `enabled: true`.
