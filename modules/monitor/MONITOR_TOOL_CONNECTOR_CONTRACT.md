# Monitor external-tool connector contract (N70, source-only)

**Status:** Contract implemented and Mock-tested. **No external tool connected.** Not a claim that the whole Monitor is modularized or LIVE accepted.

## Authority and composition

- `extension/monitor-tool-connector-registry.js` exports `globalThis.MonitorToolConnectorRegistry.create({authorize, verifyReceipt?, onChange?})`.
- The registry only owns presentation-visible tool inventory, lifecycle, operation deduplication, in-flight/busy state, receipt projection and UNKNOWN hold. It must not execute PowerShell, control processes/Chrome, or open Native/BCT ports.
- Tool adapters are supplied by the composition root via `register({id, capabilities, connect, disconnect, status, request})`. Registering never connects or launches.
- Each adapter must provide its own already-authorized backend access. BCT Core is the authority for Work, Operation, exact request digest, expiry, approval, lease and effect receipts. The UI **does not issue approvals** and a local `ok` flag alone is not proof.
- No new external application, process, RPC endpoint, host or credential is provisioned by this contract.

## Public interface

```text
registry.register(adapter)                       -> snapshot
registry.unregister(toolId)                      -> Promise<true> (disconnected, no UNKNOWN)
registry.list()                                  -> readonly snapshots
registry.snapshot(toolId)                        -> readonly snapshot
registry.connect(toolId, exactContext)           -> Promise<receipt>
registry.status(toolId, exactContext)            -> Promise<receipt>
registry.request(toolId, capability, payload, exactContext) -> Promise<receipt>
registry.disconnect(toolId, exactContext)        -> Promise<receipt>
registry.reconcile(toolId, verifiedProof)         -> Promise<receipt>
```

Adapter ports receive an object `{capability, payload, context}` and must return a durable result with exactly matching `workId`, `operationId`, `requestHash` and `outcome`. An input `exactContext` includes all of `workId`, `operationId`, 64-character requestHash, and optional approvalRef. The injected `authorize(exact)` must return verified matching `toolId`, action, capability, workId, operationId and requestHash together with `ok:true`; no adapter is invoked if that proof is absent. The backend must enforce expiration, one-use, permission and exact target identity.

A result is marked `APPLIED` only when the adapter returns exact matched proof. Nonmatching results or post-dispatch errors are `UNKNOWN`. Explicit matched `NOT_APPLIED` is preserved. Repeated exact operation IDs reuse a single promise/result; the same operation ID with a changed target, capability, hash or payload is rejected. No automatic retry or polling occurs.

## Lifecycle and recovery

States: `DISCONNECTED, CONNECTING, CONNECTED, DISCONNECTING, BUSY, ERROR, UNKNOWN`. `onChange` emits typed immutable tool snapshots; `needsReconciliation` marks an UNKNOWN. Unknown blocks connect, disconnect and new commands while allowing read-only status. Status alone does not clear the hold.

`reconcile` is an **explicit receipt verification** gate. The injected `verifyReceipt({toolId, original, proof})` must attest `final:true` and exact original tool/work/operation/requestHash and final outcome. It does not invoke the command or silently retry. If not injected, UNKNOWN remains blocked.

## Safety & test plan

Mock and static tests: `tools/check_monitor_tool_connector_registry.js`. Covered: port validation, registration, explicit connect/disconnect, authorized status, exact command, denied authorization, duplicate operation, altered operation identity/payload, invalid capabilities, injected execution errors, UNKNOWN hold, read-only status continuity and exact receipt reconciliation.

The contract is loaded before generated `monitor.js` by `extension/desktop.html`. It is dormant: no adapter is registered, no user interface dispatch is attached, and no Work or operation is sent in LIVE.

## Future adapter review requirements

1. Document exact tool ID/capabilities and endpoint ownership; keep credentials outside Monitor storage.
2. BCT policy must prove Work, operation, request digest, target, expiry and approval; verify identity again at the effect boundary.
3. The adapter must return a terminal durable receipt or `UNKNOWN`, never merely a successful HTTP response.
4. Use explicit user-triggered connect/disconnect; do not add side-effectful heartbeat polling.
5. Isolated Mock and fault-injection tests, then guarded candidate CI, supervisor integration, LIVE installation and physical Windows acceptance.
6. Keep existing BCT/RCC/Native implementation as the one execution authority. Do not duplicate process/Chrome/PowerShell operations in Monitor.

## Outstanding Monitor modularization boundaries

This contract does **not** make NodePanel DOM, desktop stage/strip interactions, Recovery trash/closed-conversation UI, Diagnostics command UI, or the remaining lexical cross-domain state independent. Their acceptance remains separate and the candidate must stay `PARTIAL` until all have approved tests and ownership proofs. Native provenance 2 files and MemoryGuard integration remain HOLD.

## Diagnostics command view integration (N70 follow-up)

The composition root now mounts `MonitorDiagnosticsCommandView` inside the existing diagnostics panel. It displays **승인된 진단 명령 미연결** until a genuine approved adapter is injected. No command button is enabled by default.

- Interface: `create({host,document,prepare?,run?,reconcile?}) -> {setCommands,render,request,resolveUnknown,snapshot}`.
- Command list entries: exact `{id,label,toolId,capability}`. A button may be enabled only when both `prepare` and `run` are supplied by the authorized composition root; the UI does not synthesize Work IDs, Operation IDs or approval tokens.
- `run` returns `monitor.tool.operation.v1` with exact toolId, capability, workId, operationId and requestHash. A mismatch, lost response or post-dispatch exception is `UNKNOWN`, blocking subsequent execution until exact `monitor.tool.reconciliation.v1` proof.
- The UI is not an approval authority; runtime `prepare/run/reconcile` must be connected via the existing `MonitorToolConnectorRegistry` and BCT security boundary. No provider wired in this PR.
- Mock tests: `check_monitor_diagnostics_command_view.js` and `check_monitor_tool_connector_registry.js`. No real external tool, PowerShell or Chrome effect was performed.
