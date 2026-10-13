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
- Follow-up acceptance renamed the active remote tunnel to `BCT Control Private`, refreshed the
  installed `BCT Control` 1.0.0 app, and verified an exact 21-tool BCT catalogue.
- BCT ChatGPT New Tab and BCT Auto Proxy were loaded as separate 1.0.0 modules. NewTab redirect,
  RCC exact-once tab creation and the Proxy backend cutover were accepted live.
- The legacy ACT MCP supervisor/child on 18769 and isolated ADC agent on 18766 were retired after
  exact elevated process evidence became available. BCT Core, tunnel, Laya, RCC, Monitor and Proxy
  remained healthy.

## Durable local evidence

- `D:\BCT\data\deployments\BCT-RCC-NATIVE-HOST-CUTOVER-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-RETIRE-LEGACY-ADC-RUNTIME-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-RETIRE-LEGACY-ACT-LAYA-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-PRUNE-OFFLINE-ACT-RUNNERS-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-ARCHIVE-DISABLED-ACT-TASKS-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-RETIRE-LEGACY-ACT-MCP-20261013-02\receipt.json`
- `D:\BCT\data\migrations\BCT-RETIRE-LEGACY-ACT-ADC-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-PROXY-BACKEND-CUTOVER-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-REDUCE-ACT-RUNNER-POOL-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-ARCHIVE-LEGACY-BROWSER-MODULES-20261013-01\receipt.json`
- `D:\BCT\data\migrations\BCT-ARCHIVE-LEGACY-ACT-STARTUP-20261013-01\receipt.json`

## Deliberately not forced

- Active GitHub runners still execute from `D:\ACT`. Their pool is reduced, but path migration must
  preserve runner identity, service registration and BOOTSTRAP recovery availability.
- DesktopWindow Monitor needs a product decision on the retained minimal window/node/status surface
  before the ACT-coupled organization UI can be disabled.
- Dormant ACT direct-bridge compatibility remains in RCC source; the live BCT named-pipe path does
  not use it, but removal requires a focused Native Host rebuild and reload.

These are explicit migration gates, not hidden BCT Core dependencies.
