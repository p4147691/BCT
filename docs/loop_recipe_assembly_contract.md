# Persistent Loop assembly contract

This is a design and source-level contract only.  It does not register an MCP
command, change Chain Recipe, create a conversation, arm a Watch, or send a
message.

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
3. A route table selects an endpoint from declared required capabilities.  A
   later runtime adapter will turn that selection into a prearmed, receipted
   delivery or a local re-entry.  It is not implemented by this contract.

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

## Next implementation boundary

The next change may add Loop-only adapters for topology, Watch registration,
transport, and recovery.  Each adapter must consume a `DeliveryIntent` and
call existing BCT capabilities through their documented Operation/receipt
contracts.  It must not modify or reinterpret existing Chain records.
