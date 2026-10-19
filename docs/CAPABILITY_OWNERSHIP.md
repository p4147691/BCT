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
  VTL-owned mouse move/click/scroll/left-drag and keyboard input against an
  exact active window lease; and
- authenticated Unicode clipboard read/write receipts through the VTL-owned
  current-session helper, fenced by an exact Session Lease; raw clipboard text
  is transient output and durable evidence contains only length/hash metadata;
  and
- authenticated current-virtual-desktop window inventory plus audited exact
  activation of the non-hidden, non-minimized window bound to that lease; and
- bounded exact-EXE launch receipts plus atomic binding of the session lease
  only to a visible current-desktop window owned by the newly created PID.
- authenticated bounded Chrome `RootWebArea` element inventory plus audited
  exact ValuePattern/InvokePattern dispatch through the VTL-owned helper, fenced
  by the active tab identity, exact Window Lease, emergency stop and foreground.
- exact immutable VTL runtime verification, bounded direct scenario dispatch,
  background receipt and external evidence identity for `vtl_validate`.

These capabilities live in the BCT repository and do not import ACT runtime modules.

## BCT-owned components and external assets

The DesktopWindow Monitor source baseline lives under `modules/monitor`. Its existing Chrome
installation stays at the external extension path for compatibility. It is not a second authority;
the independent BCT Monitor is the core operational view. Monitor extension/native source is not
copied into the Core runtime release; it will use a separate exact module deployment profile when
its installation is cut over.

VTL owns its runtime installer, generic scenario drivers and result schema. BCT owns the exact
runtime-manifest verification, work-scope policy, operation receipt and dispatch boundary; product
repositories continue to own profiles, selectors, scenarios and expected results.

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
expiry and a generation-fenced emergency-stop latch. The input slices add real mouse
move/click, bounded wheel scroll/left drag, key and Unicode text input through VTL. The next slice adds bounded
current-virtual-desktop window inventory and exact leased-window activation.
BCT owns the authenticated policy, durable receipt and UNKNOWN-effect boundary;
VTL owns the Windows `SendInput` execution.  Every effect requires the exact active window lease,
revalidates the target and emergency-stop state immediately before injection, and never retries an
ambiguous partial effect.  Activation additionally revalidates virtual-desktop
identity and refuses hidden or minimized windows. Chrome content pattern execution
is owned by VTL while BCT owns its authenticated policy/receipt/UNKNOWN boundary.
Unicode clipboard access is owned by VTL's STA helper and requires a Session
Lease; BCT persists only metadata and returns clipboard text only on the first
successful direct `get` response.
Scheduled Task recovery, complete RDC parity and a misleading ADC
compatibility layer remain outside this slice.

DesktopWindow Monitor and Chrome Auto Proxy are external compatibility modules, not Core. Their
active installed paths stay fixed until their exact extension/native identities are migrated. Runner
services are operations infrastructure; they are not part of Core and do not grant BCT authority.
