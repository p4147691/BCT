# BCT RCC V1 completion

## Result

The accepted RCC implementation is preserved as BCT source and its bounded browser-control
surface is available through the common BCT core/MCP operation path. Existing Chrome
bindings and the installed extension/native host were not replaced or reconfigured.

## Source and tests

- Exact live baseline commit: `c103c8fcad0f9ab7001e06ee8370365ffc8e48d6`.
- Feature commit: `882a71c6a7eb45784c9434b8f9048538e7934946`.
- CI hardening commit: `72b50d391d5fd901696b732ac3d2779d1903112a`.
- PR #13 merge: `15f8ce551e7360ab77266c331758c0e249706d85`.
- PR CI: `38254069968` PASS; main CI: `38254397056` PASS.
- Local and hosted regression: 38/38 PASS; compile and diff checks PASS.

The hardening commit prevents Git checkout line-ending conversion under `modules/rcc/` and
reconciles a lost service shutdown response by exact PID/endpoint post-state instead of
leaving a completed stop ambiguous.

## Live acceptance

- Release SHA: `15f8ce551e7360ab77266c331758c0e249706d85`.
- Manifest: `35f4c8e2ccaa517e37b8449e888bce64f03003845abbf93e40dd6003f26288c6`.
- BCT service: PID 38252, generation 7, health contract 2, MCP ready.
- Source/runtime exact-file mismatches: 0/23.
- MCP catalogue: 15 tools; `bct_relay_browser` present in direct protocol and a fresh
  Codex process.
- Exact live RCC state: APPLIED, two open tabs, 24 preserved registrations, zero pending.
- Duplicate state operation returned its durable receipt without a second pipe call.
- Secret and authorization fields were absent from BCT output/receipt.
- Protected tab `594832035` remained open; no tab, window, message, or binding mutation was
  used for acceptance.

