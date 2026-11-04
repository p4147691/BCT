# BCT performance audit — 2026-10-15

## Finding

The 2026-10-14 main CI run `38642809660` completed 206 tests in 172.924 seconds.
Its slow-test report showed four orchestration regression tests at 5.852–5.904
seconds each.  In an isolated checkout at main `83654b51d342a66259916532b0ae064c2ad597dd`,
those same four tests took 22.370 seconds together.

Each uses `FakeRelay` with a hidden terminal result and a lost send response.
The production code correctly polls until the supplied five-second bounded
timeout and then records `UNKNOWN`; the fake fails synchronously.  These tests
exercise the timeout protocol, not a wall-clock recovery requirement.

## Change and safety boundary

The four timeout-path tests use a test-local advancing monotonic clock. Each
production polling sleep advances the fake clock by the same duration, so the
same five-second deadline, polling sequence, receipt preservation, `UNKNOWN`
handling, resource claims, and no-resend behavior are exercised without waiting
five wall-clock seconds. Production code and timeout bounds are unchanged.

## Verification

Run the four focused tests before and after the change, then the full unittest
suite, compile check, and `git diff --check`.  Compare the focused elapsed time;
the expected reduction is approximately five seconds per timeout-path test.

Observed focused timing was 22.370 seconds before and 2.633 seconds after.
With `PYTHONPATH=src` to guarantee that the isolated checkout rather than a
separate editable BCT worktree was imported, the complete suite passed: 206
tests in 160.789 seconds. The timeout-path tests no longer appeared in its
25 slowest tests.
