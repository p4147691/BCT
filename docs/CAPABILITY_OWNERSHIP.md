# BCT capability ownership

## Direct BCT platform capabilities

BCT owns the implementation, policy boundary, operation receipt and live acceptance for:

- work identity, operation idempotency, resource claims and handoff;
- project file read, atomic write and sensitive-path checks;
- Python tests and direct Python, PowerShell and argv execution;
- durable Python, PowerShell and argv process sessions with exact PID/fingerprint ownership;
- bounded Git commit, including task-owned new files with expected hashes;
- GitHub branch push, PR, CI status, exact merge and verified-main synchronization;
- named-profile deployment, immutable releases, exact service ownership, health and rollback;
- the authenticated BCT MCP catalogue generated from loaded executors;
- exact-instance RCC inspection and bounded browser relay mutations;
- BCT Monitor state and UI.
- authenticated current-user desktop-session status and read-only screen/window
  capture through the external VTL-owned Desktop Session Agent.
- durable BCT receipts for the VTL-owned current-session control lease and
  emergency-stop coordination boundary; and
- policy validation, durable operation fencing and audited dispatch for
  VTL-owned mouse and keyboard input against an exact active window lease.

These capabilities live in the BCT repository and do not import ACT runtime modules.

## BCT-owned components and external assets

The DesktopWindow Monitor source baseline lives under `modules/monitor`. Its existing Chrome
installation stays at the external extension path for compatibility. It is not a second authority;
the independent BCT Monitor is the core operational view. Monitor extension/native source is not
copied into the Core runtime release; it will use a separate exact module deployment profile when
its installation is cut over.

Chrome, Windows, GitHub and GPU drivers are also external assets. BCT owns the exact adapter and
receipt around them, not the products themselves.

## Project workflows, not BCT subsystems

Historical ADC tools that only serve one product or a rare repair flow are not copied into BCT core.
Examples include mobile toolchains, Chrome enterprise-policy repair, extension retirement or store
submission, package installation, remote brokers, and one-off probes or upgrades. When needed, they
run as explicit project work through BCT's normal execution and approval boundary.

This keeps the platform small without losing the ability to perform the work.

## ACT boundary

ACT remains installed as a rollback witness for older live components and protected historical work.
BCT does not need ACT to run its core, MCP, Monitor, RCC boundary, or development
workflow. No existing ACT task, Chrome tab, binding or ambiguous operation is replayed during BCT work.

The old ACT ADC MCP/controller and ACT-path Laya runtime have been retired.  The first BCT desktop
slice now owns the authenticated adapter, operation receipt and MCP image result for exact session
status and read-only capture.  VTL owns the generic per-user Windows Agent and protected named-pipe
implementation.  The second coordination slice adds a short-lived exact-target lease, automatic
expiry and a generation-fenced emergency-stop latch.  The next bounded slice adds real mouse
move/click, key and Unicode text input through VTL.  BCT owns the authenticated policy, durable receipt and UNKNOWN-effect boundary;
VTL owns the Windows `SendInput` execution.  Every effect requires the exact active window lease,
revalidates the target and emergency-stop state immediately before injection, and never retries an
ambiguous partial effect.  General window activation/mutation and program launch remain outside
this slice, as do Scheduled Task recovery, full RDC parity and a misleading ADC compatibility layer.

DesktopWindow Monitor and Chrome Auto Proxy are external compatibility modules, not Core. Their
active installed paths stay fixed until their exact extension/native identities are migrated. Runner
services are operations infrastructure; they are not part of Core and do not grant BCT authority.
