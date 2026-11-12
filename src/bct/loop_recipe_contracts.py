"""Transport-free contracts for an independently assembled persistent Loop.

This module deliberately has no dependency on Chain Recipe, MCP, the runtime,
or a browser.  It defines the stable vocabulary shared by small processing
blocks, a replaceable assembly table, and a generic continuation hand-off.

Processing blocks report facts.  They never choose an actor, a role, or a
delivery mechanism.  Those choices belong to a separately versioned route
table and to a runtime adapter that is outside this module.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Iterable


class LoopContractError(ValueError):
    """The supplied Loop assembly or continuation violates its static contract."""


_IDENTIFIER = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_REFERENCE = re.compile(r"[A-Za-z0-9_.:-]{1,160}\Z")


def _identifier(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _IDENTIFIER.fullmatch(value):
        raise LoopContractError(f"LOOP_{field.upper()}_INVALID")
    return value


def _reference(value: str, *, field: str) -> str:
    if not isinstance(value, str) or not _REFERENCE.fullmatch(value):
        raise LoopContractError(f"LOOP_{field.upper()}_INVALID")
    return value


def _names(values: Iterable[str], *, field: str) -> tuple[str, ...]:
    result = tuple(values)
    if len(result) != len(set(result)):
        raise LoopContractError(f"LOOP_{field.upper()}_DUPLICATE")
    for value in result:
        _identifier(value, field=field)
    return result


@dataclass(frozen=True)
class ProcessingBlock:
    """A reusable capability block, intentionally unaware of route/role names."""

    block_id: str
    consumes: tuple[str, ...]
    produces: tuple[str, ...]

    def __post_init__(self) -> None:
        _identifier(self.block_id, field="block_id")
        object.__setattr__(self, "consumes", _names(self.consumes, field="input_slot"))
        object.__setattr__(self, "produces", _names(self.produces, field="output_slot"))


@dataclass(frozen=True)
class AssemblyLink:
    """One static connection between processing blocks.

    ``when`` is an outcome fact, not a named actor or delivery route.
    """

    source_block_id: str
    outcome: str
    target_block_id: str

    def __post_init__(self) -> None:
        _identifier(self.source_block_id, field="source_block_id")
        _identifier(self.outcome, field="outcome")
        _identifier(self.target_block_id, field="target_block_id")


@dataclass(frozen=True)
class AssemblyTable:
    """A declarative block graph.  It performs no work and selects no endpoint."""

    assembly_id: str
    blocks: tuple[ProcessingBlock, ...]
    links: tuple[AssemblyLink, ...]
    entry_block_id: str

    def __post_init__(self) -> None:
        _reference(self.assembly_id, field="assembly_id")
        if not self.blocks:
            raise LoopContractError("LOOP_ASSEMBLY_BLOCKS_REQUIRED")
        ids = tuple(block.block_id for block in self.blocks)
        if len(ids) != len(set(ids)):
            raise LoopContractError("LOOP_ASSEMBLY_BLOCK_DUPLICATE")
        _identifier(self.entry_block_id, field="entry_block_id")
        if self.entry_block_id not in ids:
            raise LoopContractError("LOOP_ASSEMBLY_ENTRY_UNKNOWN")
        seen = set()
        for link in self.links:
            if link.source_block_id not in ids or link.target_block_id not in ids:
                raise LoopContractError("LOOP_ASSEMBLY_LINK_BLOCK_UNKNOWN")
            key = (link.source_block_id, link.outcome)
            if key in seen:
                raise LoopContractError("LOOP_ASSEMBLY_LINK_AMBIGUOUS")
            seen.add(key)

    def next_block(self, source_block_id: str, outcome: str) -> str | None:
        _identifier(source_block_id, field="source_block_id")
        _identifier(outcome, field="outcome")
        for link in self.links:
            if (link.source_block_id, link.outcome) == (source_block_id, outcome):
                return link.target_block_id
        return None


@dataclass(frozen=True)
class Endpoint:
    """A Loop-local execution endpoint; its display role is intentionally external."""

    endpoint_id: str
    capabilities: frozenset[str]

    def __post_init__(self) -> None:
        _reference(self.endpoint_id, field="endpoint_id")
        object.__setattr__(self, "capabilities", frozenset(
            _names(tuple(self.capabilities), field="capability")))


@dataclass(frozen=True)
class Continuation:
    """Durable, route-neutral work that may later be delivered or resumed."""

    continuation_id: str
    loop_id: str
    source_block_id: str
    next_block_id: str
    revision: int
    operation_id: str
    watch_id: str
    receipt_ref: str
    required_capabilities: frozenset[str]
    artifact_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field in ("continuation_id", "loop_id", "operation_id", "watch_id", "receipt_ref"):
            _reference(getattr(self, field), field=field)
        _identifier(self.source_block_id, field="source_block_id")
        _identifier(self.next_block_id, field="next_block_id")
        if type(self.revision) is not int or self.revision < 0:
            raise LoopContractError("LOOP_REVISION_INVALID")
        object.__setattr__(self, "required_capabilities", frozenset(
            _names(tuple(self.required_capabilities), field="capability")))
        object.__setattr__(self, "artifact_refs", tuple(
            _reference(value, field="artifact_ref") for value in self.artifact_refs))


@dataclass(frozen=True)
class EndpointBinding:
    """Replaceable route-table row: required capabilities map to one endpoint."""

    required_capabilities: frozenset[str]
    endpoint_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "required_capabilities", frozenset(
            _names(tuple(self.required_capabilities), field="capability")))
        _reference(self.endpoint_id, field="endpoint_id")


@dataclass(frozen=True)
class RouteTable:
    """Policy-only endpoint selection; processing blocks never own this decision."""

    bindings: tuple[EndpointBinding, ...]

    def resolve(self, continuation: Continuation,
                endpoints: Iterable[Endpoint]) -> Endpoint:
        by_id = {endpoint.endpoint_id: endpoint for endpoint in endpoints}
        matches = [binding for binding in self.bindings
                   if binding.required_capabilities == continuation.required_capabilities]
        if len(matches) != 1:
            raise LoopContractError("LOOP_ROUTE_BINDING_REQUIRED")
        endpoint = by_id.get(matches[0].endpoint_id)
        if endpoint is None:
            raise LoopContractError("LOOP_ROUTE_ENDPOINT_UNAVAILABLE")
        if not continuation.required_capabilities.issubset(endpoint.capabilities):
            raise LoopContractError("LOOP_ROUTE_CAPABILITY_MISMATCH")
        return endpoint


@dataclass(frozen=True)
class DeliveryIntent:
    """A generic hand-off request.  A runtime adapter owns any external effect."""

    continuation: Continuation
    source_endpoint_id: str
    target_endpoint_id: str

    def __post_init__(self) -> None:
        _reference(self.source_endpoint_id, field="source_endpoint_id")
        _reference(self.target_endpoint_id, field="target_endpoint_id")


def prepare_delivery(*, continuation: Continuation, source_endpoint_id: str,
                     route_table: RouteTable, endpoints: Iterable[Endpoint]) -> DeliveryIntent:
    """Select an endpoint without sending, waking, or changing any receipt."""
    _reference(source_endpoint_id, field="source_endpoint_id")
    target = route_table.resolve(continuation, endpoints)
    return DeliveryIntent(continuation=continuation, source_endpoint_id=source_endpoint_id,
                          target_endpoint_id=target.endpoint_id)
