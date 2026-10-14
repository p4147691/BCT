"""Explicitly invoked LIVE acceptance; read metadata and compile a specified source checkout."""
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


async def run(args):
    source, runtime = Path(args.source).resolve(), Path(args.runtime).resolve()
    headers = {"Authorization": "Bearer " + (runtime / "mcp.token").read_text().strip()}

    @asynccontextmanager
    async def connect():
        async with httpx.AsyncClient(headers=headers, timeout=40) as client:
            async with streamable_http_client(args.url, http_client=client) as (reader, writer, _):
                async with ClientSession(reader, writer) as session:
                    await session.initialize()
                    yield session

    async def call(session, name, arguments):
        result = await session.call_tool(name, arguments)
        if result.isError:
            raise RuntimeError(f"{name} failed: {result.content}")
        return result.structuredContent

    paths = ["pyproject.toml", "AGENTS.md", "src/bct/service.py", "src/bct/core/models.py",
             "src/bct/features/verification.py", "src/bct/features/github.py"]
    steps = [{"id": f"file-{index}", "capability": "read", "arguments": {"path": str(source / path)}}
             for index, path in enumerate(paths)]
    steps.append({"id": "compile", "capability": "test", "arguments": {
        "cwd": str(source), "kind": "py_compile", "targets": ["src/bct/features/verification.py"], "timeout_s": 60}})
    work = args.prefix + "-work"
    operation = args.prefix + "-combined"
    async with connect() as session:
        catalog = await session.list_tools()
        assert "bct_verify" in {tool.name for tool in catalog.tools}
        compact = await call(session, "bct_status", {})
        assert compact["core"]["ready"] and compact["runtime"]["release_sha"] == args.expected_sha
        full = await call(session, "bct_status", {"compact": False})
        compact_bytes = len(json.dumps(compact).encode())
        full_bytes = len(json.dumps(full).encode())
        await call(session, "bct_work_create", {"work_id": work,
            "request_summary": "bounded verification LIVE acceptance", "roots": [str(source)],
            "actions": ["read", "test", "verify", "github_pr_status"]})
        observations = []
        tick = time.perf_counter()
        for index, step in enumerate(steps):
            result = await call(session, "bct_" + step["capability"], {
                "work_id": work, "operation_id": args.prefix + f"-separate-{index}", "arguments": step["arguments"]})
            assert result["outcome"] == "APPLIED"
            observations.append(result["evidence"])
        separate_ms = (time.perf_counter() - tick) * 1000
        assert observations[-1]["status"] == "PASS"
        tick = time.perf_counter()
        accepted = await call(session, "bct_verify", {
            "work_id": work, "operation_id": operation, "arguments": {"steps": steps}})
        assert accepted["state"] in {"RUNNING", "FINISHED"}
    # Closing the session before retrieval exercises durable worker independence.
    async with connect() as session:
        receipts = 0
        for _ in range(4):
            result = await call(session, "bct_operation_get", {
                "work_id": work, "operation_id": operation, "wait_seconds": 25})
            receipts += 1
            if result["state"] == "FINISHED":
                break
        combined_ms = (time.perf_counter() - tick) * 1000
        assert result["outcome"] == "APPLIED", result
        assert result["evidence"]["status"] == "PASS"
        for index, individual in enumerate(observations[:-1]):
            grouped = result["evidence"]["steps"][index]["evidence"]["items"][0]
            assert individual["sha256"] == grouped["sha256"]
        duplicate = await call(session, "bct_verify", {
            "work_id": work, "operation_id": operation, "arguments": {"steps": steps}})
        assert duplicate["duplicate"] and duplicate["evidence"] == result["evidence"]
        ci = None
        if args.pr:
            ci_id = args.prefix + "-ci-wait"
            await call(session, "bct_github_pr_status", {"work_id": work, "operation_id": ci_id,
                "arguments": {"repository": "p4147691/BCT", "number": args.pr,
                    "expected_head": args.pr_head, "required_checks": ["test"], "wait_seconds": 60}})
            for _ in range(4):
                ci = await call(session, "bct_operation_get", {"work_id": work, "operation_id": ci_id, "wait_seconds": 25})
                if ci["state"] == "FINISHED":
                    break
            assert ci["outcome"] == "APPLIED" and ci["evidence"]["checks_ready"], ci
        summary = {"status": "PASS", "transport": "direct authenticated Streamable HTTP",
            "release_sha": args.expected_sha, "operation_id": operation,
            "steps": len(steps), "matching_file_hashes": len(paths), "duplicate_preserved": True,
            "disconnect_reconnect": True, "separate_calls": len(steps), "combined_calls": 1 + receipts,
            "separate_ms": round(separate_ms, 3), "combined_ms": round(combined_ms, 3),
            "compact_status_bytes": compact_bytes, "full_status_bytes": full_bytes,
            "ci_wait": ci["evidence"] if ci else None}
        if args.output:
            destination = Path(args.output)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
        print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--runtime", required=True)
    parser.add_argument("--expected-sha", required=True)
    parser.add_argument("--prefix", required=True)
    parser.add_argument("--url", default="http://127.0.0.1:18790/mcp")
    parser.add_argument("--pr", type=int)
    parser.add_argument("--pr-head")
    parser.add_argument("--output")
    asyncio.run(run(parser.parse_args()))
