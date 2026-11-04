# BDC — BCT Desktop Control

BDC is the BCT module for desktop and native UI control.  The name replaces
the old product-level `ADC` label for capabilities maintained by BCT.

BDC is deliberately not part of `src/bct/core`.  Core authenticates the
caller, decides policy, records one operation and prevents duplicate effects.
BDC validates and executes the concrete desktop action and reports evidence
through that operation.

## Migration boundary

Only generally useful desktop primitives are migrated:

- exact process/window inspection;
- bounded launch and focus with PID/fingerprint evidence;
- keyboard, pointer and window geometry actions;
- exact endpoint/readiness evidence for BCT-owned processes.

Legacy ADC repair tools, product release helpers and one-off scripts remain
project work.  They are not copied into BDC merely because ADC once hosted
them.  Until each primitive has a BCT acceptance test, the existing ADC
runtime is a rollback source and is not dual-dispatched.

## Representative command and recipes

`bct_desktop` is the human-facing bookshelf for these existing parts.  It is
deliberately plan-only: `action=catalog` shows the component map and
`action=plan` returns the ordered public capabilities for one recipe.  The
effectful capabilities still run as separate Work-scoped Operations so their
Lease, exact target, receipt, UNKNOWN and recovery boundaries stay visible.

The initial recipes are:

- `inspect_desktop` — session, window and visual observation;
- `use_application` — currently only an exact Chrome or Explorer target, activation, fresh UIA element, one action, independent UIA readback and release; other applications are unsupported;
- `use_chrome` — exact Chrome target and bounded page UI action, preferring CDP or a dedicated Chrome API when available; independent metadata readback does not prove value changes, so mark them UNVERIFIED without stronger evidence;
- `arrange_window` — partial recipe for exact Chrome/Explorer window state or geometry change, followed by independent window-list readback;
- `launch_program` — partial recipe for exact executable, PID/window evidence, independent window-list readback and release;
- `open_folder` — the existing Explorer open/reconcile recipe.

This makes BDC easy to invoke aggressively without creating a second hidden
desktop executor.  New recipes must compose these public parts or add one
small independently tested primitive; they must not bypass BCT Operations.

