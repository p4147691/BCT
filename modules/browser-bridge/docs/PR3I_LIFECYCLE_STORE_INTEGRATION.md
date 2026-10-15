# Browser Bridge PR3-i — isolated lifecycle/store integration

PR3-i joins the already opt-in PR3-f lifecycle with the explicitly injected
PR3-h DPAPI file store only inside a disposable test directory.  It proves
that metadata can be reopened, a next generation becomes active, the retired
generation's protected file is removed, and revocation removes the remaining
Bridge-only file after fail-closed metadata revocation.

It supplies no default directory, ACL policy, Windows account selection,
listener, registry entry, Chrome extension, or runtime activation.  A failed
external cleanup never reactivates a retired or revoked binding; operating
system cleanup/recovery policy remains an activation-gate design task.
