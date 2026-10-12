# DesktopWindow Monitor source provenance

Baseline recovery date: 2026-10-12.

The files in this directory were imported byte-for-byte from the active DesktopWindow Monitor
installation at `D:\ChromeExtensions\DesktopWindow-Monitor` before BCT-specific semantic changes.
The imported scope is deliberately bounded to:

- `extension/`: the active unpacked Chrome extension source and documentation;
- `native/src/`: maintained Native Messaging host source;
- the two active Native Messaging manifests directly below `native/`;
- `tools/`: active source validators and deployment checks.

Inactive versioned native binaries, recovery backups, Python bytecode, `.reload-token` and
`.reload-ack` runtime markers were not imported.  Chrome profile data, extension storage, ACT
state, secrets and historical bindings were not copied.

The pre-import active tree was not a Git checkout.  Its authority was established by
`ACTIVE_SOURCE.md`, `extension/AGENTS.md`, the active Chrome installation path and Native Messaging
manifest paths.  The exact imported baseline is recorded by `BASELINE_SHA256.txt`.

This recovery commit changes no live Monitor file.  Future BCT changes must use a named exact-file
deployment with source/live SHA fencing, backup, atomic replacement and rollback.
