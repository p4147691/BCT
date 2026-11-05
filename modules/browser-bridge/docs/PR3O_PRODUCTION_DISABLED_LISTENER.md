# Browser Bridge PR3-o — production-disabled listener composition

PR3-o composes the previously accepted boundaries without activating a
product listener. `ProductionDisabledListener` requires explicit
`enabled=True` and `fixture_only=True` values plus injected
`BindingLifecycle`, `DpapiFileSecretStore`, client verifier and endpoint
objects. It owns no pipe name, credential path, process launcher, registry
entry or runtime configuration. The ordinary one-argument Native Messaging
path and `persistent_host.py` do not import or construct it, and environment
variables cannot enable it.

The Windows proof uses one pipe connection for the complete pre-read gate.
`BridgeWindowsActivationPolicy` verifies the credential root/file owner and
protected DACL, pipe DACL, client logon session, client PID and executable
SHA-256. The C# helper then waits for Python authorization of the current
binding before sending the client its write gate. It reads exactly one bounded
PR3-k transport frame through the existing PR3-m reader; Python passes those
same bytes directly to PR3-l `PipeRelay`, which retains PR3-e proof, generation
and replay fencing. A client ACK is emitted only after Core dispatch and the
result publication callback succeed. A post-dispatch disconnect is UNKNOWN
and is never resent.

All Windows entry points are explicit test arguments. The seal command is a
fixture-only bridge between a newly created disposable PR3-h file and the
exact PR3-n ACL. It refuses missing, non-canonical, reparse or non-child paths
and never creates or deletes them. Listener shutdown disposes only the owned
pipe/process connection; binding metadata, replay sequence and credential
files survive restart. Provision, rotation and revocation remain exclusively
owned by PR3-f/PR3-h.

This checkpoint does not add a service/runtime entry point, real capability
issuer, browser recipient identity, extension installation, Chrome completion
observer, HKCU registration or packaging. It does not authorize an operational
credential root. Product activation and Chrome E2E remain blocked on those
later checkpoints.
