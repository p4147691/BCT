# Browser Bridge PR3-j — Windows protected-pipe probe

PR3-j is a disposable test harness for the Windows primitives required by a
future Bridge-only IPC endpoint.  It creates one random same-user named pipe,
obtains the connected client's PID with `GetNamedPipeClientProcessId`, hashes
that client's executable, and accepts a one-byte probe only when the digest
matches the expected value.  A wrong digest fails closed.

The harness contains no Bridge secret, Core request, registry entry, persistent
endpoint, Chrome access, or production Native Messaging change.  It is invoked
only by explicit test-only command arguments and ends when the test exits.
It establishes a mechanical prerequisite, not an activation approval: a real
endpoint still needs its Bridge-only lifecycle, framed peer adapter, cleanup
receipt, and separate approval.

`PipeOptions.CurrentUserOnly` proves only the current Windows-user restriction
for this probe.  It is not the final same-session/process policy: the later
endpoint must use an explicit DACL with the logon-session SID where required,
and preserve the PID/executable-digest check shown here.
