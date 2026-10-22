# BCT Chat Stream RCC Connection Watch V1

Status: ISOLATED / FOCUSED_TESTS_PASS / NO_LIVE_RERELOAD

## Objective

For an explicitly opted-in BCT Work with an existing durable chat-stream
checkpoint, recognize meaningful ChatGPT connection transitions using the
RCC extension's existing `state`/endpoint activity telemetry and persist the
corresponding `chat_stream_transport_reports` observation. After one proven
`DISCONNECTED -> CONNECTED` transition within the same RCC session,
automatically recompute BCT's source-receipt-based, **no-effect** resume
inspection. This does not restart a model's internal stream or run the saved
next step.

## Binding and authorization

The owning Work must call `bct_orchestrate(operation="chat-stream-rcc-watch-bind")`
with exact `session_id` (chat stream ID), RCC `instance_id`, and
`conversation_key`. A checkpoint must already exist for the same Work.
The binding includes assignment epoch and is immutable. An authorized caller
can read `chat-stream-rcc-watch-status` for the latest watch state and a
fresh safe resume inspection after a verified reconnect; the status operation
never reads or mutates any other Work's data.

No watch => no polling of any RCC instance. Work reassignment/finished Work
disables background polling of its old binding. A unique live endpoint UUID,
OPEN presence and an explicit boolean `connection.disconnected` must all
agree before a transition is recorded.

## Observation transport

An opt-in Core daemon polls the existing authenticated RCC named-pipe
`state` command approximately every 15 seconds. It never submits a ChatGPT
prompt, changes a tab, opens Chrome, reloads RCC or claims a relay resource.
It uses the existing C# Native Host's same-session protected pipe identity
checks, and the existing RCC content script's `connectionProblem()` signals.
The RCC RC9 candidate additionally recognizes the user-observed Korean
"메시지 전송 시간이 초과되었습니다" UI alert and bounded English timeout
variants; it continues to ignore text inside conversation messages.

Unobserved/ambiguous endpoints and an RCC pipe outage are **not** network
reconnection proof. Session/extension reload resets the transition baseline,
never generating a spurious CLIENT_RECONNECTED. Ordinary ChatGPT generating
is not a transport state and is not a trigger. Reports use deterministic
idempotent event identities and the same Work's durable transport table.
Client banner content, prompts and credentials are not persisted.

## Recovery safety

On a verified reconnect, an inspection checks the exact saved BCT Operation
receipt fingerprint and outcome. FINISHED/APPLIED allows a proposed next
step; UNKNOWN means STOP_UNKNOWN_NO_RESEND, missing/drifted receipts block,
and RUNNING requires the original execution to be checked. No consumer of
these reports is granted dispatch/retry permission. Core health shows a
small observation status, not the user messages.

## Limits and testing

This is a 15-second sampled observation, so transient toasts may be missed.
Only an opted-in Work that already stores a checkpoint can be monitored.
Core source and RCC candidate builds must both pass exact SHA/CI before
any production upgrade. Source release SHA in an existing checkpoint is
metadata, not cryptographic attestation of a deployed Core.

Simulated E2E covers disconnect, reconnect, stale epoch, wrong/ambiguous
conversation UUID, RCC unavailability, RCC session change, ordinary
GENERATING, duplicate events, Core restart and UNKNOWN no-resend.
The RCC candidate RC9 has 52 exact files and LIVE RC8 as its rollback
inventory; existing browser tabs/storage and the original Phase 7A
NEEDS_REVIEW deliveries are not modified by this PR.
