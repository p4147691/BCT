from pathlib import Path
import argparse
import json
import urllib.error
import urllib.request


def fetch_json(base, path, timeout):
    url = base.rstrip("/") + path
    request = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read().decode("utf-8", "replace")
            try:
                body = json.loads(raw)
            except Exception:
                body = {"_raw": raw[:4000]}
            return {"status": response.status, "body": body}
    except urllib.error.HTTPError as error:
        raw = error.read().decode("utf-8", "replace")
        try:
            body = json.loads(raw)
        except Exception:
            body = {"_raw": raw[:4000]}
        return {"status": error.code, "body": body}
    except Exception as error:
        return {"status": None, "error": type(error).__name__ + ": " + str(error)}


def main():
    parser = argparse.ArgumentParser(
        description="Read-only live check for DesktopWindow Monitor organization authority endpoints"
    )
    parser.add_argument("--base", default="http://127.0.0.1:18765")
    parser.add_argument("--timeout", type=float, default=1.5)
    args = parser.parse_args()

    paths = [
        "/health",
        "/organization/hierarchy",
        "/organization/resources",
        "/organization/ai-nodes",
        "/organization/workspaces",
    ]
    responses = {path: fetch_json(args.base, path, args.timeout) for path in paths}
    errors = []
    facts = {}

    def body(path):
        value = responses[path].get("body")
        return value if isinstance(value, dict) else {}

    for path in paths:
        response = responses[path]
        payload = body(path)
        if response.get("status") != 200:
            errors.append({"kind": "http_status", "path": path, "status": response.get("status"), "error": response.get("error")})
            continue
        if payload.get("ok") is not True:
            errors.append({"kind": "endpoint_not_ok", "path": path, "body": payload})

    health = body("/health")
    if health and health.get("service") != "Agent Orchestrator":
        errors.append({"kind": "unexpected_service", "service": health.get("service")})

    hierarchy = body("/organization/hierarchy")
    resources = body("/organization/resources")
    ai_nodes = body("/organization/ai-nodes")
    workspaces = body("/organization/workspaces")

    expected_hierarchy = {
        "organization_generation": int,
        "edges": list,
        "detached_children": list,
        "node_controls": list,
        "resource_edges": list,
    }
    for key, expected_type in expected_hierarchy.items():
        if key not in hierarchy or not isinstance(hierarchy.get(key), expected_type):
            errors.append({"kind": "hierarchy_shape", "key": key, "expected": expected_type.__name__})

    if not isinstance(resources.get("organization_generation"), int):
        errors.append({"kind": "resources_shape", "key": "organization_generation", "expected": "int"})
    if not isinstance(resources.get("resource_edges"), list):
        errors.append({"kind": "resources_shape", "key": "resource_edges", "expected": "list"})
    if not isinstance(resources.get("llm_nodes"), list):
        errors.append({"kind": "resources_shape", "key": "llm_nodes", "expected": "list"})
    if not isinstance(ai_nodes.get("nodes"), list):
        errors.append({"kind": "ai_nodes_shape", "key": "nodes", "expected": "list"})
    if not isinstance(workspaces.get("workspaces"), list):
        errors.append({"kind": "workspaces_shape", "key": "workspaces", "expected": "list"})

    hg = hierarchy.get("organization_generation")
    rg = resources.get("organization_generation")
    if isinstance(hg, int) and isinstance(rg, int) and hg != rg:
        errors.append({"kind": "generation_mismatch", "hierarchy": hg, "resources": rg})

    facts["base"] = args.base.rstrip("/")
    facts["organization_generation"] = hg
    facts["edge_count"] = len(hierarchy.get("edges") or []) if isinstance(hierarchy.get("edges"), list) else None
    facts["detached_count"] = len(hierarchy.get("detached_children") or []) if isinstance(hierarchy.get("detached_children"), list) else None
    facts["node_control_count"] = len(hierarchy.get("node_controls") or []) if isinstance(hierarchy.get("node_controls"), list) else None
    facts["resource_edge_count"] = len(resources.get("resource_edges") or []) if isinstance(resources.get("resource_edges"), list) else None
    facts["llm_node_count"] = len(resources.get("llm_nodes") or []) if isinstance(resources.get("llm_nodes"), list) else None
    facts["ai_node_count"] = len(ai_nodes.get("nodes") or []) if isinstance(ai_nodes.get("nodes"), list) else None
    facts["workspace_count"] = len(workspaces.get("workspaces") or []) if isinstance(workspaces.get("workspaces"), list) else None
    facts["endpoint_status"] = {path: responses[path].get("status") for path in paths}

    result = {"ok": not errors, "errors": errors, "facts": facts}
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
