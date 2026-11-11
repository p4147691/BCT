# Chain Recipe Supervisor-only review diagnostic — isolated

## Exact original and continuation
- Work: bct-rcc-fastpath-independent-supervisor-20261111
- Original Direction: direction-2d92684d9caa4551b89bd728; decision NEW_TASK; assessment {}; target_conversation_key ""; target_deliveries []; no chain_task/operation/send_operation; chain_state NOT_PLANNED.
- Follow-up parent-linked diagnosis: direction-pr471-pr473-review-hold-20261111, decision HOLD, parent_direction_id direction-2d92684d9caa4551b89bd728, parent_step_id PREPARE_SEND_DIRECTION, branch_kind DIAGNOSIS; no send or target.
- N23 exact UUID 6aeed472-62d8-83ee-b86d-16cd79d48132, role Supervisor, globally unassigned. N39 and N40 are unrelated busy work; never use as a fabricated Manager/Worker.
- PR #471 exact SHA f6e8a3dd74da8c8ef31939f9afd22787170c4479; previous full CI #42937777114 success.
- PR #473 exact SHA d3eb60ba2c2ec0c0d6edcc5da57be5ceef27c0ba; previous full CI #42943748342 success.
- Do not infer independent Supervisor approval from CI or from the local review worktree tests.

## Root cause
1. mcp_server.validate_assessment formerly returned NOT_PROVIDED on missing assessment even for a fresh USER NEW_TASK. Chain Recipe save therefore persisted a structurally empty Direction that was impossible to send; later send returned CHAIN_RECIPE_DIRECTION_HAS_NO_TARGETS.
2. chain_direction.validate_direction_assessment for NEW_TASK requires manager_conversation_key, worker_conversation_key, supervisor_conversation_key with distinct identities, plus targets including the initial Worker. resolve_direction_network further requires confirmed actual Manager/Worker/Supervisor roles and matching Manager/Worker network. A global Supervisor-only review target is not expressible in this existing contract.
3. Naming N23 in prose does not create an exact structured target. Reclassifying Supervisor N23 as Worker, assigning N39/N40 roles, choosing unrelated Manager/Worker, or changing the conversation network would be unsafe and unauthorized.
4. Existing parent Direction is immutable. A separate HOLD diagnosis retains a real exact parent link; it does not pretend that N23 received a message.

## Minimal isolated fix and test
- Branch fix/chain-newtask-assessment-preflight-20261111 from unchanged local main 76e5cb1c333a2a22cd0765e729af71ded10612d9.
- src/bct/mcp_server.py: for a fresh source_kind USER decision NEW_TASK and assessment omitted, reject BEFORE persisting with CHAIN_DIRECTION_ASSESSMENT_REQUIRED and the existing assessment_contract schema. Preserve legacy MANAGER_RETURN handling and HOLD.
- tests/test_chain_newtask_assessment_preflight.py tests missing and empty assessment, fully declared 3-role assessment save without send, HOLD compatibility, and Supervisor-only rejection. Existing tests/test_chain_direction.py remains unchanged and passes.
- scripts/build_component_library.py --write --reviewed and check ensure generated source hash synchronization.
- This prevents future blank user NEW_TASK Directions but DOES NOT add a new Supervisor-only execution route or repair the existing immutable Direction.

## Remaining blocker
- Design and independently review an explicit Supervisor-only review pathway, with confirmed global Supervisor UUID, declared Manager return identity when available, exact target and receipt identity, Work authorization, no synthetic Worker/Manager role, no network updates, no UNKNOWN replay. A new path would require dedicated schema/route/security tests and separately approved exact-SHA integration.
- No N23 review request sent and no approval receipt. Do not advance PR471/PR473 to main or LIVE until a genuine independent Supervisor review is performed.
- No RCC install, MCP tool refresh, shared worktree edits, role changes, or runtime deployment.
