"""Run the one-shot hosted durable-orchestration acceptance against LIVE BCT.

This script deliberately uses a fresh authenticated MCP session, exact observed
RCC conversations, one immutable operation ID per effect, and result-only receipt
polling after the chain is submitted.  It never clears RCC state or retries a
different operation when an effect is UNKNOWN.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import time
from contextlib import asynccontextmanager
from pathlib import Path

import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client


async def run(args: argparse.Namespace) -> None:
    runtime = Path(args.runtime).resolve()
    headers = {
        "Authorization": "Bearer " + (runtime / "mcp.token").read_text().strip()
    }

    @asynccontextmanager
    async def connect():
        async with httpx.AsyncClient(headers=headers, timeout=45) as client:
            async with streamable_http_client(
                args.url, http_client=client
            ) as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    yield session

    async def call(session: ClientSession, name: str, arguments: dict):
        result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"{name} failed: {result.content}")
        return result.structuredContent

    run_id = args.run_id.strip()
    if not run_id or not run_id.replace("-", "").isalnum():
        raise ValueError("run-id must contain only letters, digits, and hyphens")
    if "548e7866" in run_id:
        raise ValueError("the quarantined first LIVE chain cannot be reused")
    work_id = f"BCT-DURABLE-ORCHESTRATION-LIVE-E2E-{run_id}"
    session_id = f"durable-orch-live-{run_id}"
    chain_operation_id = f"durable-orch-live-chain-{run_id}"
    nodes = json.loads(Path(args.nodes_json).read_text(encoding="utf-8"))
    expected_node_ids = {
        "manager-primary", "worker-latency",
        "worker-recovery", "manager-backup",
    }
    if not isinstance(nodes, list) or {
        str(item.get("node_id")) for item in nodes
    } != expected_node_ids:
        raise ValueError("nodes-json must define exactly four fresh E2E nodes")

    async with connect() as session:
        catalogue = await session.list_tools()
        names = {tool.name for tool in catalogue.tools}
        assert "bct_orchestrate" in names and len(names) == 24, sorted(names)
        status = await call(session, "bct_status", {})
        assert status["core"]["ready"] is True
        assert status["runtime"]["release_sha"] == args.expected_sha
        instances = status["monitor"]["rcc"]["instances"]
        observed = next(
            item for item in instances if item["instance_id"] == args.instance_id
        )
        assert observed["background_build_id"] == args.expected_rcc_build

        await call(session, "bct_work_create", {
            "work_id": work_id,
            "request_summary": (
                "One-front-door durable manager-worker LIVE E2E using exact open "
                "RCC conversations, two worker diagnostics, manager takeover, "
                "synthesis, and no human relay"
            ),
            "roots": [
                r"D:\BCT\source", r"D:\BCT\runtime",
                r"D:\ChromeExtensions\RCC",
            ],
            "actions": ["orchestrate", "read"],
        })
        started = await call(session, "bct_orchestrate", {
            "work_id": work_id,
            "operation_id": f"durable-orch-live-session-start-{run_id}",
            "arguments": {
                "operation": "session-start", "session_id": session_id,
                "objective": (
                    "Use two existing analysis nodes to find a concrete remaining "
                    "BCT orchestration bottleneck and recovery improvement, transfer "
                    "manager ownership, then synthesize one bounded next action."
                ),
                "acceptance": {
                    "two_exact_worker_results": True,
                    "manager_takeover": True,
                    "one_synthesis": True,
                    "no_human_relay": True,
                },
            },
        })
        assert started["outcome"] == "APPLIED", started
        synced = await call(session, "bct_orchestrate", {
            "work_id": work_id,
            "operation_id": f"durable-orch-live-node-sync-{run_id}",
            "arguments": {
                "operation": "node-sync", "session_id": session_id,
                "instance_id": args.instance_id, "nodes": nodes,
                "timeout_s": 30,
            },
        })
        assert synced["outcome"] == "APPLIED", synced
        attachments = synced["output"]["attachments"]

        def attachment(node_id: str) -> dict:
            matches = [
                item for item in attachments
                if item["node_id"] == node_id and item["active"]
                and item["relay_role"]
            ]
            assert len(matches) == 1, (node_id, matches)
            return matches[0]

        primary = attachment("manager-primary")
        latency = attachment("worker-latency")
        recovery = attachment("worker-recovery")
        backup = attachment("manager-backup")
        manager = await call(session, "bct_orchestrate", {
            "work_id": work_id,
            "operation_id": f"durable-orch-live-manager-select-{run_id}",
            "arguments": {
                "operation": "manager-takeover", "session_id": session_id,
                "expected_manager_epoch": 0,
                "manager_node_id": "manager-primary",
                "reason": "Select the user-facing manager before delegation",
                "evidence": {"attachment_id": primary["attachment_id"]},
            },
        })
        assert manager["outcome"] == "APPLIED", manager
        chain_arguments = {
            "operation": "chain-run", "session_id": session_id,
            "manager_epoch": 1, "timeout_s": 900,
            "tasks": [
                {
                    "assignment_id": "live-latency-review",
                    "worker_node_id": "worker-latency",
                    "attachment_id": latency["attachment_id"],
                    "instruction": (
                        "Analyze this verified evidence only: Core main/LIVE SHA is "
                        f"{args.expected_sha}; RCC build is "
                        f"{args.expected_rcc_build}. Identify one remaining operational latency "
                        "bottleneck in the manager-worker flow and one measurable, "
                        "low-risk follow-up check. Do not call tools or change state."
                    ),
                    "acceptance": {
                        "one_bottleneck": True, "one_measurable_check": True,
                        "read_only": True,
                    },
                },
                {
                    "assignment_id": "live-recovery-review",
                    "worker_node_id": "worker-recovery",
                    "attachment_id": recovery["attachment_id"],
                    "instruction": (
                        "Review these verified invariants: operation-ID idempotency, "
                        "UNKNOWN no-retry, exact attachment generation, manager epoch "
                        "fencing, SQLite executor lease, and atomic recovery receipts. "
                        "Identify one realistic recovery edge case still worth a future "
                        "test and rate its impact. Do not call tools or change state."
                    ),
                    "acceptance": {
                        "one_edge_case": True, "impact_rating": True,
                        "read_only": True,
                    },
                },
            ],
            "takeover": {
                "manager_node_id": "manager-backup",
                "reason": "Planned manager failover acceptance after worker results",
                "evidence": {"planned": True, "prior_manager_epoch": 1},
            },
            "synthesis": {
                "assignment_id": "live-manager-synthesis",
                "manager_node_id": "manager-backup",
                "attachment_id": backup["attachment_id"],
                "instruction": (
                    "Act as the replacement manager. Combine the two exact worker "
                    "results into one concise priority decision: confirmed observation, "
                    "impact, and one bounded follow-up. Do not invent evidence."
                ),
                "acceptance": {
                    "uses_both_results": True, "one_priority": True,
                    "bounded_follow_up": True,
                },
            },
        }
        submitted = await call(session, "bct_orchestrate", {
            "work_id": work_id, "operation_id": chain_operation_id,
            "arguments": chain_arguments,
        })
        assert submitted["state"] in {"RUNNING", "FINISHED"}, submitted

    # Reconnect before observing completion to prove the chain is independent of
    # the initiating client and all progress is recovered from durable receipts.
    began = time.perf_counter()
    async with connect() as session:
        receipt = None
        for _ in range(40):
            receipt = await call(session, "bct_operation_get", {
                "work_id": work_id, "operation_id": chain_operation_id,
                "wait_seconds": 25,
            })
            if receipt["state"] == "FINISHED":
                break
        assert receipt is not None and receipt["outcome"] == "APPLIED", receipt
        snapshot_result = await call(session, "bct_orchestrate", {
            "work_id": work_id,
            "operation_id": f"durable-orch-live-status-{run_id}",
            "arguments": {"operation": "status", "session_id": session_id},
        })
        assert snapshot_result["outcome"] == "APPLIED", snapshot_result
        snapshot = snapshot_result["output"]["snapshot"]
        current = snapshot["session"]
        assignment_states = {
            item["assignment_id"]: item["state"]
            for item in snapshot["assignments"]
        }
        assert current["state"] == "FINISHED", current
        assert current["manager_node_id"] == "manager-backup", current
        assert current["manager_epoch"] == 2, current
        assert assignment_states == {
            "live-latency-review": "APPLIED",
            "live-recovery-review": "APPLIED",
            "live-manager-synthesis": "APPLIED",
        }, assignment_states
        dispatches = [m for m in snapshot["mailbox"] if m["kind"] == "DISPATCH"]
        results = [m for m in snapshot["mailbox"] if m["kind"] == "RESULT"]
        consumed = [
            m for m in results
            if m["assignment_id"] in {
                "live-latency-review", "live-recovery-review"
            } and m["consumed_at"] is not None
        ]
        assert len(dispatches) == 3 and len({m["message_id"] for m in dispatches}) == 3
        assert len(results) == 3 and len(consumed) == 2
        duplicate = await call(session, "bct_orchestrate", {
            "work_id": work_id, "operation_id": chain_operation_id,
            "arguments": chain_arguments,
        })
        assert duplicate["duplicate"] is True
        assert duplicate["evidence"] == receipt["evidence"]

    report = {
        "status": "PASS",
        "release_sha": args.expected_sha,
        "rcc_build": args.expected_rcc_build,
        "work_id": work_id,
        "session_id": session_id,
        "chain_operation_id": chain_operation_id,
        "manager_before": "manager-primary",
        "manager_after": current["manager_node_id"],
        "manager_epoch": current["manager_epoch"],
        "assignment_states": assignment_states,
        "dispatch_count": len(dispatches),
        "result_count": len(results),
        "consumed_worker_results": len(consumed),
        "duplicate_replayed": False,
        "client_reconnected": True,
        "elapsed_ms_after_submit": round((time.perf_counter() - began) * 1000, 3),
        "terminal_summary": current["terminal_summary"],
    }
    destination = Path(args.output).resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--nodes-json", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--instance-id", required=True)
    parser.add_argument("--expected-rcc-build", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18790/mcp")
    asyncio.run(run(parser.parse_args()))
