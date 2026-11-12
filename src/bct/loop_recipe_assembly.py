"""Default, role-neutral assembly for the persistent Loop Recipe.

The table is deliberately only a map.  It is not a runtime, an MCP command,
and does not create a network, arm a Watch, or perform an external action.
"""
from __future__ import annotations

from bct.loop_recipe_contracts import AssemblyLink, AssemblyTable, ProcessingBlock


def persistent_loop_assembly() -> AssemblyTable:
    """Return the standard block graph without embedding any endpoint decision."""
    blocks = (
        ProcessingBlock("resume", ("continuation", "receipts"),
                        ("current_context",)),
        ProcessingBlock("direction", ("current_context", "instruction"),
                        ("direction_revision",)),
        ProcessingBlock("topology", ("direction_revision",),
                        ("endpoint_set",)),
        ProcessingBlock("plan", ("direction_revision", "endpoint_set"),
                        ("execution_plan",)),
        ProcessingBlock("execute", ("execution_plan",),
                        ("progress_delta", "artifacts")),
        ProcessingBlock("assess", ("progress_delta", "artifacts"),
                        ("outcome", "continuation_request")),
        ProcessingBlock("complete", ("outcome",), ("completion_record",)),
    )
    links = (
        AssemblyLink("resume", "ready", "direction"),
        AssemblyLink("direction", "ready", "topology"),
        AssemblyLink("topology", "ready", "plan"),
        AssemblyLink("plan", "ready", "execute"),
        AssemblyLink("execute", "ready", "assess"),
        AssemblyLink("assess", "continue", "plan"),
        AssemblyLink("assess", "wait", "resume"),
        AssemblyLink("assess", "handoff", "plan"),
        AssemblyLink("assess", "blocked", "resume"),
        AssemblyLink("assess", "complete", "complete"),
    )
    return AssemblyTable("persistent-loop-v1", blocks, links, "resume")


def persistent_loop_outline() -> list[dict[str, object]]:
    """A display-only view used by docs/tests; it performs no route selection."""
    assembly = persistent_loop_assembly()
    return [
        {
            "block_id": block.block_id,
            "consumes": list(block.consumes),
            "produces": list(block.produces),
            "links": [
                {"outcome": link.outcome, "target_block_id": link.target_block_id}
                for link in assembly.links if link.source_block_id == block.block_id
            ],
        }
        for block in assembly.blocks
    ]
