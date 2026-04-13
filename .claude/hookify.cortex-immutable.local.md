---
name: cortex-genome-immutable
enabled: true
event: file
action: warn
conditions:
  - field: file_path
    operator: regex_match
    pattern: \.reap/genome/
---

**Genome file edit detected.** Genome files should be modified through `/cortex-update`, not edited directly. This ensures changes are tracked in the lineage and reviewed deliberately.

If you're running `/cortex-init` or `/cortex-update`, this warning is expected — proceed normally.
