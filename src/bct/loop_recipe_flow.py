"""Effect-free engine joining Loop blocks through five standard links.

Callers run a processing block and give its declared result to this engine.
The engine returns a next in-turn block or a durable continuation request; it
never selects a role, creates a Watch, or performs an external effect.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from bct.loop_recipe_contracts import AssemblyTable, Continuation, LoopContractError


class LinkKind(str, Enum):
    """The only public ways a processing block may finish."""

    CONTINUE = "continue"
    WAIT = "wait"
    HANDOFF = "handoff"
    COMPLETE = "complete"
    BLOCKED = "blocked"


@dataclass(frozen=True)
class BlockResult:
    """Facts reported by one processing block, without an endpoint or transport."""

    block_id: str
    link: LinkKind
    artifact_refs: tuple[str, ...] = ()
    required_capabilities: frozenset[str] = frozenset()


@dataclass(frozen=True)
class FlowAdvance:
    source_block_id: str
    next_block_id: str
    link: LinkKind
    requires_continuation: bool


class LoopFlowEngine:
    """Validate a result against the declarative assembly table."""

    def __init__(self, assembly: AssemblyTable):
        self.assembly = assembly

    def advance(self, result: BlockResult) -> FlowAdvance:
        if not isinstance(result, BlockResult):
            raise LoopContractError("LOOP_BLOCK_RESULT_REQUIRED")
        if result.block_id not in {block.block_id for block in self.assembly.blocks}:
            raise LoopContractError("LOOP_BLOCK_RESULT_SOURCE_UNKNOWN")
        next_block = self.assembly.next_block(result.block_id, result.link.value)
        if next_block is None:
            raise LoopContractError("LOOP_ASSEMBLY_LINK_REQUIRED")
        return FlowAdvance(
            source_block_id=result.block_id,
            next_block_id=next_block,
            link=result.link,
            requires_continuation=result.link in {
                LinkKind.WAIT, LinkKind.HANDOFF, LinkKind.BLOCKED,
            },
        )

    def continuation(self, *, advance: FlowAdvance, continuation_id: str,
                     loop_id: str, revision: int, operation_id: str,
                     watch_id: str, receipt_ref: str,
                     result: BlockResult) -> Continuation:
        """Build an envelope only for a non-immediate link."""
        if not advance.requires_continuation:
            raise LoopContractError("LOOP_CONTINUATION_NOT_REQUIRED")
        if result.block_id != advance.source_block_id or result.link != advance.link:
            raise LoopContractError("LOOP_CONTINUATION_RESULT_MISMATCH")
        return Continuation(
            continuation_id=continuation_id,
            loop_id=loop_id,
            source_block_id=advance.source_block_id,
            next_block_id=advance.next_block_id,
            revision=revision,
            operation_id=operation_id,
            watch_id=watch_id,
            receipt_ref=receipt_ref,
            required_capabilities=result.required_capabilities,
            artifact_refs=result.artifact_refs,
        )
