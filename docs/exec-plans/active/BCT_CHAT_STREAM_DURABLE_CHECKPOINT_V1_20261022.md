# BCT Chat Stream Checkpoint V1 — isolated implementation

Status: ISOLATED / EXPLICIT-INVOCATION / NO_LIVE_RELOAD

## Two separate failure domains

A ChatGPT client may display a stream/network/timeout warning while BCT
operations finish normally. A UI warning, a GENERATING indicator, or recovery
of a WebSocket cannot prove that a filesystem/remote/Chrome operation applied
or did not apply. BCT Operation receipts are authoritative for BCT effects.
Client transport observations are **untrusted reports only**.

**BCT cannot automatically resume the interrupted internal ChatGPT text
generation.** This candidate does not intercept ChatGPT's proprietary stream
or promise automatic event delivery. A caller (operator, authorized RCC
connector or future listener) must invoke the status inspection when it is
back online. The response is a no-effect proposal, never autonomous replay.

## Persistent contract

Two append-only SQLite tables in the existing BCT Store:

- `chat_stream_checkpoints`: Work ID, stream ID, sequential step ID and index,
  exact source Operation ID, source state/outcome, SHA-256 of the scoped
  operation receipt, caller-reported exact source release SHA, proposed next
  step and timestamp. All steps are immutable. The release SHA is metadata:
  verifying the installed Core release requires separate `bct_status` proof.
- `chat_stream_transport_reports`: scoped immutable client-report incident
  ID and normalized transport signal. It cannot grant execution authority.

New `bct_orchestrate` operations, all scoped to the original owning Work:

- `chat-stream-checkpoint`: requires `session_id` (stream ID), `sequence`,
  `step_id`, `source_operation_id`, `source_release_sha`, `next_step`.
  For step N+1, previous saved source receipt must still be immutable, FINISHED
  and APPLIED. Duplicate exact step is idempotent; conflicts are denied.
- `chat-stream-report`: requires `session_id`, `incident_id`, `signal`
  in CONNECTED, DISCONNECTED, STREAM_TIMEOUT, WAITING_FOR_REPLY,
  CLIENT_RECONNECTED, CLIENT_UNOBSERVED. This is **not** a BCT outcome.
  On a CLIENT_RECONNECTED event the same request immediately includes a
  `resume_inspection` assembled from BCT's live authoritative operation
  receipts. This is a no-effect, no-replay proposal. An authorized external
  event detector must report the event; this does not listen to ChatGPT's
  private stream.
- `chat-stream-resume-inspect`: requires `session_id`; reads every saved
  scoped Operation receipt again and verifies its original evidence digest.
  It returns a read-only plan and does not call the saved `next_step`.

Decision rules: APPLIED + FINISHED + immutable receipt can propose next step;
UNKNOWN blocks with STOP_UNKNOWN_NO_RESEND; incomplete source waits; failed
or NOT_APPLIED requires operator review; missing/drifted original receipt
blocks; connection-recovered signal does not override any of those states.
All source operations must belong to the exact same Work and principal.
No foreign Work inspection, no credential/prompt/body persistence.

## Failure simulation and LIVE boundaries

Run `tests/test_chat_stream_checkpoint.py` to simulate long-stream timeout,
client reconnection, UNKNOWN effects, receipt alteration, duplicate messages,
Windows process restart (reopening the same SQLite), stale Work scopes and
read-only `bct_orchestrate` integration. No network, browser or RCC mutation.
Full exact-head CI is required before an official Core-only deployment.
No RCC reload, relay send or original NEEDS_REVIEW delivery state transition
is in scope. Preserve existing N13/N14/N21/N22/N23, N24 and all UNKNOWN receipts.

Future UX event integration requires an independent connector with explicit
consent/authorization and cannot automatically reconstruct lost model
generation. Checkpoints are safe resumability metadata, not new dispatch rights.
