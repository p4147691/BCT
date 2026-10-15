# Browser Bridge PR3-n — disposable Windows activation-policy proof

PR3-n proves the remaining Windows policy boundary without activating a
listener. The explicit fixture path creates a new temporary credential root,
a non-secret placeholder file and a random named pipe whose owner and
protected DACL are checked against the current user and logon SID. The pipe
also reports its connected client session through
`GetNamedPipeClientSessionId`; a lookup failure or mismatch is rejected before
the first payload byte is read. The disposable client waits for an explicit
policy-verified byte before it is permitted to write the request; a denied
client records that it exited without writing.

The owner/DACL is re-read after the pipe connects. Unexpected ACEs, inherited
ACLs, a pre-existing target, a reparse target and modified root, file or pipe
security descriptors fail closed. Cleanup removes only the root and file
created by that fixture. Tests verify that pre-existing and junction targets
and their sentinel files are preserved.

This remains a fixture-only proof. Its two command-line switches are
unreachable from the normal one-argument Native Messaging origin path. It has
no binding provider, peer secret, PR3-k frame, PR3-l dispatch, default path,
runtime registration, listener loop, Chrome profile or HKCU entry.

The DACL admits the current logon SID and LocalSystem and records the current
Windows user as owner. This follows the Windows logon-session access-control
model, but it is not a sandbox against a malicious process already running as
the same account and able to exercise owner privileges. PR3-m executable
attestation, PR3-e proof/sequence validation and the future narrowly scoped
capability/ACK authority remain mandatory independent checks.

The next checkpoint may compose a production-disabled listener only through
explicit configuration. It must reuse `BindingLifecycle`,
`DpapiFileSecretStore`, the PR3-k codec and PR3-l `PipeRelay`; it may not copy
their lifecycle, wire, replay or UNKNOWN/no-resend behavior.
