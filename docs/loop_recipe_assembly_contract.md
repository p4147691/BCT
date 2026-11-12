# Persistent Loop assembly contract

This contract is implemented by the separate `bct_persistent_loop_recipe`
public command. It does not change Chain Recipe or the retained
`bct_loop_recipe` command.

For extension decisions and examples, see
[`loop_recipe_assembly_guide.md`](loop_recipe_assembly_guide.md).

## Three independently replaceable layers

```text
processing blocks  ->  assembly table  ->  continuation gateway
```

1. A processing block reports facts and artifacts.  It has no role name,
   endpoint choice, or delivery code.
2. The assembly table maps a fact outcome to the next processing block.  It
   never selects an endpoint or performs an effect.
3. A route table selects an endpoint from declared required capabilities. The
   Loop-only runtime adapter turns that selection into a prearmed, receipted
   delivery or local re-entry through existing BCT capabilities.

## Boundary rules

- Existing Chain Recipe code, its state transitions, and public commands are
  not imports or mutation targets of the contracts.
- A Loop continuation carries the original operation, Watch, receipt and
  revision.  A route change cannot replace those recovery identities.
- Missing, ambiguous, unavailable, or incapable endpoint bindings fail closed.
- `SELF`, `SUPERVISOR`, and other display roles belong to a Loop-local topology
  adapter.  They are deliberately absent from processing-block contracts.

## Current default assembly

```text
resume -> direction -> topology -> plan -> execute -> assess
                                           |            |
                                           | continue   | complete
                                           +---- plan   +---- complete
```

This is a processing graph, not a delivery graph.  The `assess` block reports
whether more work exists; a route table and a future generic continuation
gateway choose where that next execution occurs.

## Runtime boundary

Loop-only topology, Watch, transport, synchronization, and recovery adapters
consume the Loop records and call existing BCT capabilities through their
documented Operation/receipt contracts. They do not modify or reinterpret
existing Chain records. A new run stores the original instruction, Direction,
exact Manager and Supervisor UUIDs, and a Loop-specific network ID. The
topology action creates that new network and assigns only those exact members.

If the Supervisor does not exist, the separate `prepare_supervisor` action
reuses the existing create-chat, exact first-send, bootstrap Delayed Send Watch,
and Node Info capabilities. A new conversation has no UUID before its first
submitted message, so this bounded bootstrap is the only create/send-before-
Watch exception. The Watch accepts only the exact creation and send receipts
and a zero-response baseline. Repeating the same operation IDs reconciles those
receipts and never creates or sends again. `start` remains state-only and is
called only after the resulting exact Supervisor UUID is freshly observable.

`WAIT` and `HANDOFF` create durable Continuations before any effect. Repeating
the same continuation is read-only; changing its target, return endpoint, or
payload is a conflict. `UNKNOWN` enters reconciliation and `sync` checks the
same delayed Watch instead of issuing a new Operation. Node recovery uses the
unchanged Check, Recheck, Pause, Prepare Replace, and Commit Replace ledger
behind a Loop-specific adapter.
