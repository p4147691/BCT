# Code Block Scan V1

`scan_code_blocks` is a read-only, Work-scoped recipe for turning an unfamiliar
codebase into a reviewable block map. It scans source files, static declarations,
imports, exact duplicate bodies, size and branch-density signals, and produces:

- Block Map
- Block Candidates (`primitive`, `module`, `partial_recipe`, `full_recipe`)
- Refactor Targets
- Block Cards
- Component Catalog Candidates
- risk-ordered work list

The report is evidence for review, not runtime proof. Every card labels unknown
outputs and static-only failure conditions. File, byte, and block budgets are
bounded; an incomplete scan reports `PARTIAL` instead of claiming completion.
The file hash index and scan fingerprint provide the stable boundary for a later
incremental scanner.

`organize_code_blocks` is deliberately separate and is not implemented by this
read-only command. A future organizing recipe may change code only after the user
selects candidates, with its own write/test authority, diff review, rollback, and
component-catalog registration checks.
