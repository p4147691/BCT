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

