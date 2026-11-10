"""Build/check the shipped read-only library from existing authoritative docs.

--write --reviewed means the editor reviewed the prose against changed sources.
The mechanical check detects stale copies, not the truth of arbitrary prose.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MANUAL = "docs/CHAIN_MESSAGE_RECIPE_V2.md"
CATALOGUE = "docs/component-library.v1.json"
OUTPUT = "src/bct/data/component-library.json"
FLOW_SOURCES = (
    "src/bct/mcp_server.py", "src/bct/chain_direction.py", "src/bct/chain_execution_plan.py",
    "src/bct/chain_entry_policy.py", "src/bct/chain_recipe_blocks.py", "src/bct/chain_recovery_context.py",
    "src/bct/automatic_chain_recovery.py", "src/bct/automatic_manager_rebinding.py",
    "src/bct/automatic_prepared_replacement.py",
    "src/bct/runtime_server.py",
    "src/bct/send_delayed_message.py", "src/bct/continuation_primitives.py",
    "src/bct/component_library.py", "src/bct/conversation_network.py",
    "src/bct/features/conversation_network.py", "src/bct/node_recovery.py",
    "src/bct/task_message.py", "src/bct/core/chat_stream_rcc_watch.py",
    "src/bct/delivery_continuation_recovery.py",
)


def source_text(path: Path) -> str:
    # Checkout CRLF and Windows' system code page must not change this contract.
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


def build_bundle(root: Path = ROOT) -> dict:
    catalogue = json.loads(source_text(root / CATALOGUE))
    sources = {MANUAL, CATALOGUE, *FLOW_SOURCES}
    for part in catalogue["components"]:
        sources.update(entry["path"] for entry in part["implementation"])
    hashes = {name: hashlib.sha256(source_text(root / name).encode("utf-8")).hexdigest()
              for name in sorted(sources)}
    fingerprint = hashlib.sha256(json.dumps(hashes, sort_keys=True).encode()).hexdigest()
    text = source_text(root / MANUAL)
    return {"schema": "bct.component-library.bundle.v1", "source_fingerprint": fingerprint,
            "source_hashes": hashes, "catalogue": catalogue,
            "manual": {"path": MANUAL, "text": text,
                       "sha256": hashlib.sha256(text.encode("utf-8")).hexdigest()}}


def render(bundle: dict) -> str:
    return json.dumps(bundle, ensure_ascii=False, indent=2) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--reviewed", action="store_true")
    args = parser.parse_args()
    expected = render(build_bundle())
    target = ROOT / OUTPUT
    if args.write:
        if not args.reviewed:
            parser.error("Review the manual against source, then use --write --reviewed.")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(expected, encoding="utf-8", newline="\n")
        print("Component library generated from reviewed source and documentation.")
        return 0
    if not target.is_file() or source_text(target) != expected:
        print("STALE_COMPONENT_LIBRARY: review the manual, then run --write --reviewed.")
        return 1
    print("Component library matches source and manual.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
