# BCT → MemoryGuard verified node/process projection (isolated contract)

- project_node_processes(authenticated_bct_status, renderer_observations=..., os_process_observations=...) is read-only and cannot authorize closing, model unload or process termination.
- BCT already knows permanent N<number> and conversation UUID; RCC knows exact instance/session/tab/window IDs and tab title. These alone CANNOT attribute a renderer's memory to one node.
- verified_bindings[] conforms to MemoryGuard node_memory_view.verified_node(): pid, create_time, node, conversation_uuid, target_id, tab_title, target_process_exclusive and observation timestamp.
- Accept only trusted RCC per-tab renderer evidence: browser renderer process ID vs OS PID distinguished, renderer type, full task-tab list proving exclusivity, exact RCC identities, and OS PID/create-time live readback, all <=120 seconds old.
- Missing, stale, conflicting, duplicated or shared-renderer evidence emits NO verified bindings and keeps '미확인'.
- Existing RCC v1.0.60 manifest lacks processes permission; official Chrome extensions documentation lists processes as Dev channel availability. Do not assume it works in user's stable Chrome.
- No permission install, Chrome/RCC/Core restart, CDP attachment, extra surveillance server or live state change is approved.
- This library is intentionally not hooked into live MCP/Monitor/status while current node-status and Monitor owners are active. Future integration requires a trusted PID producer and owner review.
- Source: https://developer.chrome.com/docs/extensions/reference/api/processes

Acceptance: only unique exact single-tab renderer proof yields MemoryGuard-compatible binding; unavailable/shared/stale maps stay unverified.