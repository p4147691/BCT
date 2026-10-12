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
- Laya discovery, lifecycle, advisory inference and deterministic fallback;
- BCT Monitor state and UI.

These capabilities live in the BCT repository and do not import ACT runtime modules.

## BCT-owned components and external assets

The DesktopWindow Monitor source baseline lives under `modules/monitor`. Its existing Chrome
installation stays at the external extension path for compatibility. It is not a second authority;
the independent BCT Monitor is the core operational view. Monitor extension/native source is not
copied into the Core runtime release; it will use a separate exact module deployment profile when
its installation is cut over.

Laya weights and Python dependencies live outside Git under `D:\BCT\models` and
`D:\BCT\local-llm`. BCT owns their configured lifecycle and evidence, while the third-party model
files and libraries remain external assets.

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
BCT does not need ACT to run its core, MCP, Monitor, Laya recommendation, RCC boundary, or development
workflow. No existing ACT task, Chrome tab, binding or ambiguous operation is replayed during BCT work.
