# BCT Monitor wallpaper clean refactor baseline — 2026-10-25

Objective: isolate desktop wallpaper pipeline, retire legacy substitution only after proven replacement. Do not delete existing BCT resources.

Existing situation: monitor.js has Actuals, Cache, Fallbacks, and restore images. Live 2.0.36 has no Windows wallpaper-change event subscriber. Native change event feature is an isolated uninstalled experiment. CLOAKED window capture and geometry placeholder are separate.

New state module: monitor-wallpaper-state.js holds only pending/captured/failed. It accepts genuine native image data, isolates each desktop, rejects stale asynchronous results by generation, and returns failure without old fake image. Pure logic only; no DOM, Native, timers, or Chrome actions.

Acceptance sequence: (1) prove real Windows event delivery, (2) connect new module to existing Native wallpaper snapshot and exact desktop background target, (3) prove live pixels match wallpaper without refresh using CDP visual inspection, (4) replace old wallpaper-specific maps and fallback only after regression, (5) deploy with installed-only Monitor changes preserved, exact SHA, backup, native compile, one approved reload; UNKNOWN never retry.

Current result: pure module and test PASS in D:\BCT\worktrees\monitor-wallpaper-minimal-20261025. Local main, runtime, active Chrome, RCC unchanged.