# Browser Bridge credential and local transport gate

Browser Bridge is an independent control client for the BCT Core. It uses its
own extension identity, Native Host registration, launcher, staging directory
and the host-only BCT MCP token. It does not reuse RCC files or the general operator
token used by another BCT client.

## Authority boundary

The current Core exposes one local BCT MCP bearer mapped to `bct-mcp-local`; it
does not yet issue a distinct Browser Bridge principal. The bearer stays inside
the Native Host and is never returned to the extension or chat. Core principal
capabilities are the upper bound for every call. Work actions describe the task
but are not a second permission list. Each effectful tool still requires exact
operation identity, current Core policy and resource/effect fences. The
extension and Native Host cannot grant themselves another capability or turn a
denied tool into PowerShell.

The token must:

- live in a Bridge-owned file with a restrictive current-user/SYSTEM ACL;
- never enter Chrome storage, a command line, log, receipt or tool result;
- be rotated by trusted staging rather than overwritten by the extension;
- be revoked before removing an operating Host;
- connect only to the configured loopback BCT MCP endpoint.

`BCT_BRIDGE_ALLOW_LIVE_CORE=1` is a required activation flag for port 18790.
Its presence is not authorization by itself; origin, launcher/runtime digests,
token, principal, Work and Core policy must also pass.

## Browser and request boundary

Only the pinned Browser Bridge origin may launch the Native Host. Every exact
`chatgpt.com/c/<uuid>` conversation gets the same automatic transport; Monitor
Node Info and a popup click are not permission gates. Assistant text is
untrusted input and must match the strict tool envelope. The Host then verifies
the requested tool against the authenticated Core's actual MCP tool list before
one call.

A transport interruption after dispatch is `UNKNOWN`. The Bridge never retries
that request automatically. Recovery uses the original Work/Operation receipt.

## Optional protected-pipe path

The checked-in PR3 peer-binding, DPAPI and named-pipe components remain an
alternative hardened local transport. They are not silently combined with the
direct MCP path and are not required to claim the current generic tool
transport works. Enabling them is a separate release decision with its own
binding-generation and executable-proof acceptance tests.

## Activation acceptance

Before operating activation, prove all of the following on the exact candidate:

1. package, Native Host, component-library and isolated MCP tests pass;
2. exact candidate CI builds the launcher;
3. tool listing and read/control/write/execute calls pass against an isolated Core;
4. wrong origin, missing token, unregistered tool and malformed arguments fail closed;
5. a disposable Chrome profile completes the same-conversation request/result loop;
6. installation records exact source, launcher, manifest, token path, current Core principal and rollback ownership;
7. existing Chrome, RCC, BCT Core, UNKNOWN operations and Claims remain untouched.
