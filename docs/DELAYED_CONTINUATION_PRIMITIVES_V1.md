# Delayed Continuation Primitives V1

## Purpose

Replace the internally coupled Send Delayed Message implementation with a
composable continuation recipe without changing its existing public behaviour.
The original command remains a compatibility recipe during the migration.

This is a *continuation-layer* design, not the whole BCT control flow.  It
starts only after the caller has completed the ordinary BCT preflight and has
an authorized Work/context.  Delayed Send must never replace status, network,
or Work authorization commands.

## Where this fits in the complete BCT flow

```text
bct_status                         read the current Core, RCC and Monitor facts
  -> 시작 점검                         use the bct_status facts; this is not a second status read
  -> bct_check_conversation_network (when needed) read a selected conversation network and project context
  -> bct_work_create                establish the authorized Work boundary
  -> bct_set_conversation_network (when needed)  set project membership/role metadata under that Work
  -> bct_run_plan (when needed)     record a plan; it does not execute it
  -> choose one execution route
       A. session-start/node-sync -> bct_task_run -> one orchestration dispatch
       B. bct_chain_message -> prearm -> one exact Worker message -> continuation recipe
```

`bct_task_run` and `bct_chain_message` are not aliases.  The first publicly
dispatches one prepared orchestration assignment.  The second is the current
one-Worker durable message-flow entry point.  The continuation primitives
described here live only below route B after its prearm; they do not turn it
into a completed multi-worker Chain Run.

This document uses short names deliberately.  A short name is never a
permission: all external effects still require the owning Work, exact durable
identity, and an RCC observation at execution time.

## Glossary

| Short name | Meaning | Does not do |
| --- | --- | --- |
| context | A durable binding supplied by the caller: owning Work/principal, named conversation roles, assignment epoch, and current attachment observations. | Infer the active Chrome tab or grant authority from a display label. |
| watch | A request to observe one named subject until a condition is proven. | Choose a next action or send a message. |
| evidence | The exact observed facts that proved a watch condition. | Authorize a different target or a retry. |
| alarm | A durable, consumable record that a watch condition was proven. | Send anything by itself. |
| action | A requested external effect that consumes a ready alarm. | Re-observe, guess identity, or retry UNKNOWN. |
| recipe | A named composition of context, watch, alarm, and actions. | Add authority beyond its components. |

## Role slots

Do not reduce every flow to one source and one target.  A context can name the
roles used by a recipe:

```text
actor      owner/principal allowed to execute the effect
subject    conversation or resource being watched
recipient  conversation or resource receiving an effect
attachment current RCC instance/session/tab/window observation for a role
```

The durable identity for a conversation is its UUID.  Attachments are
reacquired observations and must be checked again immediately before an RCC
effect.

## Primitive contracts

```text
context_bind(...) -> context_ref
watch_arm(context_ref, subject, condition) -> watch_ref
watch_status(watch_ref) -> WATCHING | READY | CANCELLED | STALE | UNKNOWN
alarm_get(watch_ref) -> alarm_ref + evidence_ref
action_bind(context_ref, alarm_ref, kind, payload_ref) -> action_ref
action_execute(action_ref) -> receipt
```

The initial conditions are `conversation.response_finished` and
`conversation.input_ready`.  The initial action kinds are:

```text
wake            send a bounded request to inspect current state and decide
return          deliver an existing result as full text, summary, receipt, or reference
send-message    send an already hash-bound message exactly once
create-watch    start a separately authorized subsequent watch
```

`wake` is not an autonomous BCT decision engine.  It delivers a bounded
context/alarm reference to a designated conversation; the receiving agent
performs any judgment.

## Compatibility recipe: Send Delayed Message

```text
existing chain/Work context
  -> context_bind(worker subject, worker/manager recipients)
  -> watch_arm(worker, response_finished + input_ready)
  -> alarm(response-ready with exact source-response evidence)
  -> parse explicit NEXT TASK marker
  -> send-message(worker for SELF, manager for MANAGER)
```

The existing API name, input fields, receipt names, and state transitions stay
valid through this migration.  In particular, a planned BCT send remains bound
to its exact operation id and submitted-text digest.

## Safety gates

1. A watch accepts only its exact subject and expected response/source proof.
2. A ready alarm is immutable and carries evidence; it cannot be repointed.
3. An action rechecks Work owner, assignment epoch, capability, durable UUID,
   and current attachment before an external effect.
4. `UNKNOWN` is terminal for automatic execution.  It requires reconciliation,
   never a guessed resend.
5. Role labels and network metadata can help select a context but never grant
   execution authority.

## Migration gates

1. Extract pure watch-to-alarm and alarm-to-action code behind the existing
   Delayed Send API.
2. Add equivalence tests for SELF, MANAGER, incomplete input, wrong response,
   duplicate poll, cancellation, and planned-send digest/receipt proof.
3. Keep `send-delayed-message` as the first recipe and pass the existing test
   suite unchanged.
4. Add a read-only alarm/status surface before adding a new action type.
5. Add `wake` only after its exact recipient, payload bound, and receipt model
   are tested; do not use a wake to bypass a send or approval contract.
