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
incremental scanner. Each Block Card also includes an exact `file_sha256` and
`source_sha256`; the latter hashes the original decoded source slice without
discarding comments or whitespace.

`organize_code_blocks` is the separate plan/apply recipe for one selected block:

1. `action=plan` requires read authority, re-indexes the exact source file, and
   returns the old file/block hashes, normalized replacement hash, after-file
   hash, review diff, and `plan_sha256`. It does not write.
2. `action=apply` requires the exact plan values and a durable `operation_id`.
   It fails closed if the file or block drifted, assembles only that line range,
   and delegates the resulting file to the existing BCT `write` primitive.
3. The `write` primitive keeps its existing Work authorization, whole-file SHA
   precondition, temporary-file write, atomic replace, receipt, and duplicate
   operation behavior.

The source file is not polluted with marker comments and no parallel storage is
needed. The deterministic Block Index plus exact hashes are the block boundary.
Tests remain a separate caller-selected step; a successful replacement receipt
does not claim that the changed project passed its test suite.
