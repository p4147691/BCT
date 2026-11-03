# BCT Owned Extension Action V1

`bct_owned_extension_action` is the ordinary-Chat entry point for a very small
set of operations on Chrome extensions owned by BCT.

## Public contract

- Monitor reload: `{"target":"monitor","action":"reload"}`
- RCC reload: `{"target":"rcc","action":"reload","instance_id":"..."}`

No caller may provide a URL, extension ID, JavaScript, DevTools method,
function name, installed path, or raw command. Unknown keys fail closed.

## Existing blocks reused

- Monitor uses the installed `Request-MonitorDeploymentCheck.ps1` contract.
  It validates the installed extension identity and structure, publishes one
  reload-observation token, and requires the matching ACK, manifest version,
  and fresh runtime telemetry. A fixed adapter then invokes only the existing
  `monitor-reload-extension` message on the exact owned Monitor page, so an
  ordinary Chat caller does not need to focus Monitor first.
- RCC delegates to the existing `BrowserFeature` `reload-extension` operation.
  Exact instance identity, idle proof, active Delivery fencing, durable receipt,
  and UNKNOWN no-retry behavior remain unchanged.

An ACK timeout is `UNKNOWN`, not a reason to issue another reload. Ordinary
Chat can invoke the capability only inside a Work which explicitly contains
`owned_extension_action`.
