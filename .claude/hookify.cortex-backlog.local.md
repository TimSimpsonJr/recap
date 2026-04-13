---
name: cortex-backlog-prompt
enabled: true
event: stop
action: warn
conditions:
  - field: transcript
    operator: regex_match
    pattern: (architecture|convention|principle|constraint|refactor|design decision|should we change|pattern)
---

**Architectural discussion detected in this session.** Consider whether any decisions should be captured as genome changes.

To queue a genome change, create a markdown file in `.reap/life/backlog/` with the proposed change, or run `/cortex-update` to review and apply changes.
