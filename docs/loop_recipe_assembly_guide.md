# Persistent Loop block assembly guide

This guide explains how to extend the Loop without changing Chain Recipe or
embedding a route choice inside a processing block.

For ordinary assembly, start with the short Korean
[`loop_recipe_assembly_card_ko.md`](loop_recipe_assembly_card_ko.md).  This
document explains the implementation boundaries behind that card.

## The four different things

```text
Processing block: transforms Loop state into facts and artifacts.
Assembly link:    selects the next processing block for one outcome fact.
Continuation:     durable envelope used across a wait, restart, or endpoint hand-off.
Route table:      selects an endpoint that satisfies declared capabilities.
```

`Continuation` is not a processing block.  It does not plan, execute, decide,
or send.  It preserves the exact recovery identity needed by a future generic
gateway:

```text
continuation_id, loop_id, revision,
original operation_id, watch_id, receipt_ref,
required capabilities, artifact references
```

## The normal path does not need a Continuation

Use an `AssemblyLink` when the next block can run as part of the same active
turn.  For example, the standard graph connects `plan -> execute -> assess`
directly.  No Watch, endpoint selection, or delivery is implied by that link.

```text
[plan] --continue--> [execute] --continue--> [assess]
```

## When to create a Continuation

Create one only when the next processing block cannot safely run immediately:

- the active turn must wait for a response or time condition;
- the Loop must survive a process restart before continuing;
- an endpoint other than the active endpoint may perform the next block;
- an external effect requires a prearmed Watch and an original receipt;
- a human approval or external system result must be observed first.

The block reports a `continuation_request` fact.  A generic continuation
gateway persists the `Continuation`, prearms any required Watch through a
future adapter, and later re-enters the assembly at `next_block_id`.

```text
[assess]
  -> facts: incomplete + required capabilities
  -> continuation request
  -> generic continuation gateway
  -> [next endpoint, then plan]
```

The `assess` block must not contain endpoint names or call a send function.

## How to add a new processing step

Add a block if the new work changes facts or artifacts.  Give it neutral input
and output slots, then add links in the assembly table.

```text
before
  execute --continue--> assess

after adding a verification step
  execute --continue--> verify --continue--> assess
```

Only the assembly table changes around the new block.  `execute` and `assess`
do not need to learn that `verify` exists.

Use a block for: plan creation, execution, verification, result normalization,
approval evaluation, or summary generation.

Do not use a block merely to say “send to X” or “wake Y”.  Those are gateway
effects and must remain outside the processing graph.

## How to add a conditional path

Have a block emit an outcome fact such as `ready`, `continue`, `blocked`, or
`complete`.  Add the corresponding `AssemblyLink` in the table.

```text
assess --continue--> plan
assess --complete--> complete
assess --blocked--> approval_wait
```

The outcome name describes a result, not a person or a transport method.

## How to change who does the work

Do not edit the processing blocks.  Add or replace an `EndpointBinding` in the
route table.

```text
required capabilities {execute}
  -> endpoint-current          # first policy
  -> endpoint-review           # replacement policy
```

The endpoint's display role, conversation, and authentication proof are
Loop-topology adapter concerns.  They do not enter a block contract.

## How to add a new transport or Watch implementation

Do not add transport calls to a block.  Implement a Loop-only adapter behind
the generic continuation gateway.  Its required sequence is:

```text
load exact Continuation
-> verify Loop revision, Work authority, endpoint identity and readiness
-> prearm the exact Watch
-> make one receipted effect, if applicable
-> retain original operation/Watch/receipt identities
-> on UNKNOWN, reconcile the original receipt only; never create a replacement
```

Existing BCT capabilities may be called unchanged by that adapter only when
their side effects and record ownership match the Loop operation.  Chain
Recipe, its state transitions, and its public commands remain unchanged.

The production adapter is exposed through `bct_persistent_loop_recipe`. It
uses the existing BCT conversation-network, delayed-Watch, exact-message, and
Node Recovery capabilities without editing them. `WAIT` prearms the current
response and performs no initial self-send. `HANDOFF` persists first, prearms
the target response, and then makes one exact send. `sync` reads the original
Watch state; it never sends. The unchanged delayed-Watch wire vocabulary uses
`NEXT TASK — SELF` and `NEXT TASK — MANAGER`; inside this Loop the second route
means the other bound endpoint (A to Supervisor or Supervisor to A).

### Preparing a missing Supervisor

Supervisor creation is a Loop-topology adapter, not a processing block. Call
`prepare_supervisor` with one exact Manager UUID, RCC instance/window, and four
stable Operation IDs for create, first send, bootstrap Watch, and Node Info.
It reuses the existing BCT effects unchanged:

```text
verify exact Manager and RCC attachment
-> create one new chat
-> send the first Supervisor role instruction and obtain its UUID
-> bind the existing bootstrap Watch to the exact create/send receipts
-> register Supervisor Node Info
-> start the Loop with that freshly observed UUID
```

The first Watch cannot precede the first send because a new ChatGPT conversation
does not yet have a UUID. This is the same bounded bootstrap receipt rule used
for existing prepared nodes. Any ambiguous attachment or UNKNOWN receipt stops
the sequence. A retry must reuse all original Operation IDs and must not create
a replacement chat or message.

## Extension checklist

Before adding anything, answer these in order:

1. Does it transform Loop facts or artifacts? Add a processing block.
2. Does it only decide the next processing stage? Add an assembly link.
3. Does it change who may perform the next stage? Change the route table.
4. Does it cross a wait, restart, or endpoint boundary? Create a Continuation.
5. Does it cause an external effect? Implement or reuse a gateway adapter;
   never put the effect in a processing block.

If more than one answer is yes, split the change at those boundaries instead
of making one larger block.
