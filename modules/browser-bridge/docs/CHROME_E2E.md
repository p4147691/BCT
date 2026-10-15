# Real Chrome E2E gate

This is a manual, explicitly approved acceptance gate.  It is not run by CI, does not use the production BCT Core at port 18790, and must not touch RCC, LIVE work, Issue #111 records, UNKNOWN operations, or claims.

## Browser decision

Use **ordinary Chrome with a new, named test profile and Developer Mode → Load unpacked** for the first product acceptance.  Chrome documents this as the local-development installation path, and it proves the same UI-mediated installation that an operator will perform.  It also keeps the manifest-pinned ID visible before the native host allowlist is registered.

Use **Chrome for Testing (CfT) only for a later automated suite**, pinned to a version and launched by Puppeteer with `enableExtensions`.  Do not use the raw `--load-extension` path that the earlier harness used: the normal Chrome invocation was observed to end in `CHROME_EXTENSION_LOAD_BLOCKED`, so it is not the reproducible acceptance path.  CfT is appropriate for automation because its binary can be pinned, but it requires a separate approved download and test run.

Chrome references: [Load unpacked](https://developer.chrome.com/docs/extensions/get-started/tutorial/scripts-activetab), [extension E2E testing](https://developer.chrome.com/docs/extensions/how-to/test/end-to-end-testing), and [Puppeteer extension enablement](https://developer.chrome.com/docs/extensions/how-to/test/puppeteer).

## Required approval, exactly scoped

Before any real E2E, approve all of the following together:

1. Launch one ordinary Chrome process with a newly created, bridge-owned profile directory; no existing profile may be selected.
2. Use Chrome UI to enable Developer Mode and load only `modules/browser-bridge/extension` unpacked.
3. Build and stage the committed launcher into a new bridge-owned directory; no RCC executable is replaced.
4. Create one **HKCU** registration only for `com.bct.browser_bridge.prototype`, pointing to a generated bridge-owned manifest whose sole origin is `chrome-extension://acdgnmbgpkfjkckccbhmccojgigbfcge/`.
5. Create a temporary isolated BCT Core, random loopback port, test work, fixture, and token with an ACL restricted to the current user and SYSTEM.  Never use port 18790 or an operating token.
6. Perform one manual popup read of the fixture, receipt lookup, denied outside-fixture read, then a second valid read; capture only outcome/receipt metadata.
7. Remove the exact registry key, owned manifest, Core/runtime, token, fixture, staged launcher, and profile after the browser and test Core have stopped.

Approval must also name the rollback owner and confirm that a test-only HKCU key with the same name does not already exist.  If it exists, stop rather than overwrite it.

## Preflight and acceptance

Preflight must prove:

- Current source package tests pass and `git diff --check` is clean.
- The extension ID calculated from the checked-in manifest key is `acdgnmbgpkfjkckccbhmccojgigbfcge`.
- The generated host manifest's name, executable path, and sole allowed origin match the values above.
- Test paths, test profile, and target HKCU registry key do not already exist.
- The selected Chrome process is new and uses only the approved test profile.
- The isolated Core URL is loopback `/mcp` on a random port other than 18790; its token is never logged.

Record PASS only when all four browser-visible/receipt outcomes succeed: valid read, exact receipt lookup, denied outside-fixture read, and reconnect/follow-up read.  A native disconnect or ambiguous dispatch is `UNKNOWN`; do not resend the same operation.

## Rollback and cleanup

The cleanup is ordered: close only the owned Chrome process; stop only the isolated Core; verify the registry value still points to the generated manifest; delete that key; then delete owned manifest, launcher staging, Core/runtime/token/fixture, and test profile.  If ownership/value checks fail, preserve the artifact and report `CLEANUP_BLOCKED`; never delete a pre-existing key, profile, executable, BCT data, or RCC file.

`PENDING_FILE_RENAME` or a stale closed browser process is not by itself permission to reboot.  A reboot is outside this gate.
