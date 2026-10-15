# Browser Bridge PR3-m — disposable Windows relay E2E

PR3-m adds an explicit test-only C# path that is unreachable from the normal
Native Messaging origin path. On a disposable Windows runner it proves:

1. Python provisions a random 32-byte Bridge-only secret into a new temporary
   DPAPI file and records only binding metadata in the disposable Core store;
2. the built C# Host unprotects that file, creates the canonical PR3-e proof
   and PR3-k transport frame, and connects to a random same-user named pipe;
3. the pipe server obtains the connected PID and exact executable SHA-256
   before emitting the frame;
4. PR3-l rechecks that attestation against the active binding and dispatches
   through PR3-e and PR3-c into the authenticated fake Core exactly once; and
5. revocation removes the DPAPI file, process exit removes the pipe, and the
   temporary directory is deleted by the test.

The test also proves that a wrong connected-executable digest produces no
relay frame. No secret is placed in arguments, environment, SQLite, stdout,
receipts or logs; only the path to the temporary protected blob is passed to
the explicit fixture client.

This is still not product activation. `CurrentUserOnly` plus executable digest
does not finalize the logon-session/DACL policy, and the fixture commands have
no production runtime entry point. The test creates no Chrome profile, HKCU
registration, BCT LIVE record, RCC resource or persistent credential.

