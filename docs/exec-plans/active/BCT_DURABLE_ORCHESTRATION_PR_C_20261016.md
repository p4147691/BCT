# BCT Durable Orchestration PR C

Status: implementation and isolated verification in progress.  This plan is
production-disabled because Manager Wake schema 2 remains disabled by default.

## Scope and authority

BCT Core remains the only authority for Work, Policy, epoch, lease,
Assignment, decision, Outbox, result consumption, and ACK state.  RCC is a
transport and durable browser-result receipt provider.  This change does not
add another scheduler, decision engine, state ledger, HTTP receiver, or
authentication server.

PR A #149 fixes the receipt-only Manager Wake contract.  PR B #150 atomically
persists a Manager decision, optional successor Assignment, consumption
receipt, and `orchestration_dispatch_outbox`.  PR C connects that existing
Outbox to the existing RCC Worker transport and PR2 delivery state machine.

## Implemented trigger boundary

- `ManagerDecisionRecovery` invokes a callback only after the PR B SQLite
  transaction has returned successfully and created at least one delivery.
- The callback sets an in-process `threading.Event`; it carries no authority or
  payload.
- `WorkerDispatchRecovery` waits on that event with a bounded timeout.  Both an
  event and a timeout call the same idempotent, lease-fenced `run_once` path.
- If Core exits after commit but before the signal, the PENDING Outbox remains
  authoritative and polling recovers it.
- RCC `RESULT_PERSISTED` still has no trusted push path into BCT.  Worker result
  discovery therefore remains bounded polling.  Adding Native Host or Chrome
  push is outside this PR.

## Delivery and evidence states

1. PR2 reserves the exact Outbox row and the existing orchestration service
   reserves the exact Assignment in one SQLite transaction.
2. `NamedPipeRelayClient` opens the exact instance pipe, then executes a
   `before_write` fence callback immediately before bytes are written.
3. Failure before write is `CONFIRMED_NOT_APPLIED`; the Assignment and Outbox
   become terminal `NOT_APPLIED` and are never silently retried.
4. The callback commits `SEND_STARTED`.  Any subsequent timeout or transport
   ambiguity becomes `UNKNOWN`; only exact `result` lookup is allowed.
5. `host:ack submitted=true` records `DELIVERED` (submission evidence), not
   Worker result consumption or final ACK.
6. An exact `RESULT_PERSISTED` receipt must match delivery, fingerprint,
   request digest, binding receipt, instance, session, tab, conversation,
   attachment generation, and a Python recomputation of the RCC JavaScript
   `resultHash` payload.
7. Assignment completion, Manager Wake creation, and PR2
   `acknowledge_delivery` commit in one SQLite transaction.  Only then is RCC
   `result-ack` attempted.
8. Loss of the `result-ack` response retries only that ACK.  The Worker message
   is never resent.
9. The same dispatcher immediately observes the committed schema-2 Manager
   Wake and uses the existing deterministic `send-wakeback` contract. Bounded
   polling recovers a lost in-process signal or a Core restart.
10. A Manager Wake remains PENDING until the exact RCC pipe has opened. Its
    PENDING-to-DELIVERING claim occurs in the immediate-before-write callback,
    which atomically rechecks the dispatcher lease, Manager lease/epoch,
    current Work, and exact Manager attachment. UNKNOWN wakes are receipt
    lookup only and are never resent.

One singleton dispatcher lease fences parallel pollers.  A replacement may
turn a stale `RESERVED` row back into `PENDING` only after taking the expired
dispatcher lease; the old owner must pass the same live fence in its
`before_write` callback and therefore cannot write afterward.

## Compatibility and preserved state

- Existing schema 1 Wakes, Issue #111 receipts, `consumed_at`, Claim, and prior
  UNKNOWN rows are neither migrated nor replayed.
- Schema 2 remains default OFF.  The runtime dispatcher exists only when that
  existing setting is explicitly enabled after later deployment approval.
- Existing deterministic PR B delivery IDs, exact RCC fingerprint fields,
  Worker result nonce, and request digest are reused.
- PR3-a fake recipient proof is not used as production ACK evidence.
- The deployment manifest explicitly contains the new dispatcher module and
  all PR A/B runtime dependencies.

## Security and deployment gate

The installed RCC Native Host currently creates its Named Pipe without an
explicit, verified Windows `PipeSecurity` DACL or an independently proven
`CurrentUserOnly` restriction.  RCC receipts are therefore exact binding and
integrity evidence inside the current local trust boundary, but not an
independent cryptographic Worker identity proof.

`DEPLOYMENT_BLOCKED` remains mandatory until an isolated Windows test proves
the deployed pipe ACL for the intended BCT service identity and denies an
unrelated local principal.  This PR must not enable schema 2, deploy LIVE,
restart services, edit HKCU/Registry, or send real Chrome messages.

## Verification matrix

Focused tests cover:

- FOLLOW_UP Outbox dispatch and exact-once send;
- exact Worker result commit and Manager Wake creation;
- automatic Manager Wake delivery followed by a receipt-only COMPLETE decision;
- Manager Wake pipe-open failure recovery, takeover fencing, and UNKNOWN no-resend;
- RCC ACK-response loss with ACK-only recovery;
- post-write UNKNOWN with result lookup and no resend;
- confirmed pre-write non-application with zero written messages;
- current Policy and Work assignment fencing;
- tampered result hash and attachment replacement rejection;
- expired dispatcher takeover of a stale pre-write reservation;
- parallel dispatcher lease fencing;
- event hints and bounded polling using the same Core handler;
- PR1/PR2, Manager decision, RCC transport, and manifest regressions.

The final report must separate isolated fake-transport E2E from a real Chrome
E2E.  Real RCC/Chrome transmission remains prohibited in this PR.
