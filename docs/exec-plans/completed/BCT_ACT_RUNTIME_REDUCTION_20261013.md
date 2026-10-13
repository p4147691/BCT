# BCT ACT runtime reduction — 2026-10-13

## Accepted results

- BCT RCC tab control was verified after the extension and Native Host cutover against exact instance
  `6174664e1c1b4e6db1d4729c841db3c9`. Existing tabs `594832076` and `594832035` remained OPEN; no tab
  or message mutation was used for the check.
- The unused ACT ADC MCP/controller and old ACT-path Laya runtime were retired with durable,
  idempotent receipts. BCT ports 18790 and 18771 stayed healthy.
- The old ACT relay tree and five disabled scheduled tasks were archived with manifests and hashes.
- GitHub runner inventory was reduced from 34 registrations to seven live registrations by removing
  27 exact offline registrations. No local runner payload was deleted.
- DesktopWindow Monitor installed bytes match the BCT source baseline except for policy-only
  documentation. It remains installed because the old organization UI has a real backend dependency.

## Durable local evidence

- `D:\BCT\data\deployments\BCT-RCC-NATIVE-HOST-CUTOVER-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-RETIRE-LEGACY-ADC-RUNTIME-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-RETIRE-LEGACY-ACT-LAYA-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-PRUNE-OFFLINE-ACT-RUNNERS-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-ARCHIVE-DISABLED-ACT-TASKS-20261013-01\receipt.json`

## Deliberately not forced

- Four excess runner services require Windows administrator service control. An unprivileged attempt
  returned access denied without changing service state. Their listener processes were not killed.
- ADC agent port 18766 and connector port 18769 are isolated but administrator-owned; executable and
  command-line evidence is not readable from the current context, so termination remains fail-closed.
- Chrome Auto Proxy is active and its unpacked extension identity is path-derived. It needs a named,
  reversible identity migration rather than a directory move.
- DesktopWindow Monitor needs a product decision on the retained minimal window/node/status surface
  before the ACT-coupled organization UI can be disabled.

These are explicit migration gates, not hidden BCT Core dependencies.
