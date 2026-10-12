# BCT Platform Package V1

## Goal

BCT is the independent owner of the capabilities required to operate the user's development
environment.  ACT remains available only as a per-capability rollback source while migration is
in progress; BCT must not permanently import or call ACT implementation modules.

## Product boundary

BCT-owned platform capabilities:

- core identity, policy, work, operation, receipt and conflict fencing;
- project file, Git, test, GitHub, deployment and service execution;
- desktop/native execution that replaces the generally useful ADC surface;
- RCC browser relay source and control;
- DesktopWindow Monitor source, validation and bounded deployment/control;
- local decision-model discovery, health, inference and deterministic fallback;
- MCP catalogue generated from the capabilities actually loaded by the BCT runtime.

Managed projects remain outside BCT.  Windows, Chrome, GitHub, GPU drivers and model weights are
external platform assets; BCT owns their adapters, lifecycle evidence and configuration, not the
third-party binaries themselves.

## Migration rule

For every component:

1. Capture the accepted live/source baseline and provenance without semantic edits.
2. Put the maintained source and tests in the BCT repository.
3. Remove ACT-only imports and paths from the BCT implementation.
4. Pass focused and full BCT regression tests.
5. Integrate through GitHub and deploy using an exact BCT profile.
6. Verify source/runtime hashes and focused live acceptance.
7. Move only that component's ingress to BCT.  Do not dual-dispatch mutations.
8. Keep the previous live component as rollback until acceptance is durable.

ACT is not disabled before a replacement is accepted.  Existing ACT tasks, Chrome tabs, role
bindings and unknown operations are never replayed as part of migration.

## Capability decisions

### ADC

ADC is a legacy toolbox, not one indivisible service.  BCT imports the generally useful native
capabilities (read/search/write, structured process execution and inspection, tests, Git and
service health/control) into BCT's existing operation/receipt model.  Product-specific repair,
store-submission and one-off release tools stay with their owning project until explicitly
selected; they are not copied into the platform merely because they once lived in ADC.

### DesktopWindow Monitor

The accepted extension/native source and validators become BCT-owned component source.  Monitor
remains a projection and control UI, never a second identity or work authority.  Existing Chrome
installation and native-host registration stay in place until an exact-file BCT deployment is
accepted.

### Local decision model

BCT owns model discovery, endpoint health, request validation, inference receipts and fallback.
Model weights are immutable external assets under a BCT-owned model root and are not committed to
Git.  Training/evaluation corpora can be separate projects; the production provider is a BCT
capability.  Model recommendations never replace deterministic authentication, ownership or
mutation safety checks.

## Delivery slices

1. Platform inventory/status and native process execution/inspection.
2. Local decision provider and model-service ownership under `D:\BCT`.
3. Monitor exact-source baseline, validators and bounded deployment/control.
4. Remaining accepted ADC-native operations and compatibility catalogue.
5. Unified BCT release, live acceptance and ACT-dependency audit.
6. Move the canonical checkout to `D:\BCT\source` after all configured source-root references can
   be changed atomically; keep the old checkout only until the new source path is verified.

## Completion

- BCT source, runtime, data, models and worktrees have explicit BCT-owned roots.
- No BCT runtime module imports code from `D:\ACT`.
- ADC, Monitor, RCC and decision-model capabilities are visible in the BCT catalogue only when
  their executors are loaded.
- Each mutating capability uses the common operation receipt and duplicate guard.
- Existing ACT remains usable during migration and can be retired component-by-component only
  after BCT live acceptance.
- Full tests, CI, source/runtime hash checks and focused live acceptance pass.
