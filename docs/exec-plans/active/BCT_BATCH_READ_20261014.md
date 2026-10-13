# BCT batch read and round-trip reduction

Status: `LOCAL_ACCEPTED_PR_PENDING`.

## Goal

Reduce ChatGPT-to-BCT round trips for related read-only inspection while preserving the existing
work scope, operation digest, resource claim, receipt, and UNKNOWN no-retry contracts.

## Scope

- Add a bounded `operation: "batch"` mode to the existing `bct_read` capability.
- Validate every item before starting the operation and claim all item resources atomically.
- Read file content and calculate its SHA-256 from the same bytes.
- Return per-item observation evidence without persisting file content in SQLite.
- Document the shared rule: after safety conditions are fixed, combine reads inside one BCT call.
- Preserve existing `file` and `directory_tree` request and response contracts.

## Bounds

- At most 20 items per batch.
- At most 512 KiB per file and 1 MiB of file content per batch.
- At most 2,000 requested directory entries across a batch.
- Nested batches and duplicate item IDs or targets are rejected.

## Acceptance

1. Focused file and MCP tests cover mixed file/tree reads, bounds, scope rejection, partial runtime
   failure, duplicate operation behavior, and non-persistence of file content.
2. Full Python regression, compile, and diff checks pass.
3. PR CI passes and the exact merged `main` SHA is deployed to Core.
4. Authenticated LIVE MCP reads multiple real files in one operation and returns matching hashes.
5. Individual and batch calls are timed through the actual ChatGPT-visible BCT tool path where
   available; timings are reported without treating different samples as directly subtractable.

## Local evidence

- Focused development-flow tests: 11 PASS.
- Authenticated Streamable HTTP MCP integration: PASS, including one mixed file/tree batch.
- Full Python regression: 111 PASS.
- `compileall` and `git diff --check`: PASS.
- Five small files through direct Core operations: five individual operations totalled 157.844 ms;
  one batch operation took 41.698 ms in the same disposable process. This measures local operation
  overhead only and is not an estimate of the external ChatGPT round trip.
