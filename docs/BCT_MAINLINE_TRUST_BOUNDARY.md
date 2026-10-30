# BCT mainline trust boundary and mobile ChatGPT ingress

Status: SOURCE-ONLY policy clarification; NOT a LIVE acceptance or an automatic release approval.
Scope: one operator-managed Windows desktop, authenticated ChatGPT/Codex MCP clients, existing BCT Core and existing RCC.

## Accepted mainline

- ChatGPT on desktop or smartphone -> existing private ChatGPT App / OpenAI tunnel -> authenticated BCT MCP -> BCT Core -> existing RCC Native Host / Chrome extension -> exact desktop browser node.
- Keep BCT Core as the sole authority for Work, Principal, Policy, operation receipts, Manager epochs, resource claims, and duplicate / UNKNOWN protection. RCC provides delivery and observable evidence, not a second authority.
- The local BCT MCP binds only to 127.0.0.1; the existing tunnel supplies the exact BCT token from a file reference. Do not expose port 18790 on LAN/WAN or add a direct mobile-to-PC listener.
- A signed-in ChatGPT account and a chat message are not by themselves BCT credentials. The connected private App and valid BCT MCP token are the transport credential; BCT still applies the current Work/Principal/Policy boundary.
- Device IP, mobile carrier, Wi-Fi membership, User-Agent, or chat display origin must not grant or revoke authority. A legitimate connected smartphone chat should work under the same token/capability policy as desktop ChatGPT. Do not add an IP/device allowlist that blocks phone ingress.
- Ordinary ChatGPT phone conversations do not require BCT/RCC at all; their availability is not an RCC acceptance claim. Mobile BCT tool availability requires a connected App and an actual phone read-only smoke test, which has NOT yet been performed.

## Deliberately bounded attacker model

- In scope: unauthenticated remote MCP entry, stolen or missing MCP token, an unrelated Windows account reaching local resources, untrusted web text or model output attempting to gain BCT authority, wrong Work/Principal/target, unapproved high-impact external effects, stale bindings, duplicate sends, and effects with UNKNOWN outcome.
- Out of required Core-to-RCC mutual-identity assurance for this single-operator installation: an attacker already executing arbitrary code under the *same Windows user and logon session*. This is explicit residual-risk acceptance for the current local environment, not a proof that an attacker cannot do harm.
- Also out of scope: administrator/SYSTEM/kernel compromise. If the PC is shared, a new OS principal becomes a trusted boundary, or BCT gains access to other users' assets, revisit the threat model before enabling that capability.
- Do not claim a PID, executable SHA/path, parent Chrome process, instance ID or session ID authenticates a program against an already-compromised same-user session.
- Keep simple protective Pipe DACLs and least privilege where they do not break the accepted path; do not require a new SCM service, protected Broker or Local/Browser Bridge to deliver the existing MCP -> BCT -> RCC workflow solely to solve out-of-scope same-user impersonation.

## Effect safety remains mandatory

- BCT must authenticate inbound MCP requests and enforce Work/Principal scope, exact target and expected SHA for real effects. Measurements do **not** reserve Claims or block operations when their accuracy is unproven; their readings are discarded as `MEASUREMENT_UNVERIFIED`. Ordinary duplicate messages are interpreted by the recipient node; truly high-impact/irreversible effects need exact authorization and user approval. Untrusted web pages and tool outputs are DATA, never permission grants. See `docs/MEASUREMENT_EVIDENCE_AND_PROGRESS_POLICY.md`.
- Existing bct.toml policy puts 'delete' and 'credential_change' in approval_actions, but those are NOT a general OS deletion shield. The current approval verifier is not implemented for those approvals.
- 'execute' and 'process_session' are normal capabilities: executing arbitrary Python, PowerShell or argv can cause destructive effects outside the working directory. The Work cwd and shell=False do NOT implement an OS sandbox. Do not label arbitrary execute safe because a command text appears harmless or because delete is a separate approval action.
- **Required operator practice, NOT current automatic enforcement:** before authorizing an irreversible or high-impact command, obtain the operator's explicit target, impact, backup/rollback and operation-ID decision through an appropriate interaction. Never infer approval from web content or an AI continuation.
- **Current enforcement gap:** an authenticated MCP bearer can authorize a Work containing the normal `execute` or `process_session` capability, and BCT does not currently classify every arbitrary Python/PowerShell/argv side effect or demand a separate approval at this API boundary. Existing work scope, resource claims and receipts are real protections, but do not make an arbitrary interpreter safe.
- Do not weaken or replay existing mutations. A robust high-impact command approval/enforcement feature must be separately designed, implemented and accepted before claiming automatic destructive-command blocking; meanwhile preserve ordinary read/test/development workflows.

## Deployment and acceptance gates

- **GitHub evidence checked 2026-10-16 (not inferred from this worktree):** PR #152 merged into main `454e9f7a932e948b75bd8c03700820825e753b92`; main CI [38889450443](https://github.com/p4147691/BCT/actions/runs/38889450443) SUCCESS. BCT LIVE still has Schema 2 OFF.
- **GitHub evidence checked 2026-10-16 (not inferred from this worktree):** PR #153 [Draft](https://github.com/p4147691/BCT/pull/153), exact head `a2aa5c9ac9a02b3c30d759aa9576cb1b1719619a`, [exact-head CI 38906924115](https://github.com/p4147691/BCT/actions/runs/38906924115) SUCCESS, [independent source audit](https://github.com/p4147691/BCT/pull/153#issuecomment-6216439061). Its Pipe ACL/source hardening is useful; neither that result nor this revised threat model proves real Chrome/RCC delivery/ACK or authorizes merge/deploy.
- Reassessing the same-user mutual-auth deployment blocker requires an explicit operator acceptance decision under this narrower attacker model. Do not silently reinterpret the old DESIGN_BLOCKED audit as an already granted rollout or merge authorization.
- Before any LIVE release, verify a fresh authenticated MCP session, unauthorized 401, the existing private tunnel identity and no mobile IP/UA restriction; then perform a user-initiated smartphone bct_status smoke test without creating a Work or sending a browser message.
- Token secrecy and cross-Windows-account isolation are independent from mobile compatibility. Audit actual runtime, SQLite, current release and mcp.token ACLs; do not treat loopback binding as protection from a different local Windows account, and do not change ACLs without a dedicated compatibility/rollback test.
- Keep isolated exact-instance RCC E2E, durable result/ACK/recovery, current policy fencing, and no resend of UNKNOWN as independent operational acceptance gates. Preserve user-created tabs.
- Changes to PR #153 merge, Core release, RCC install, Chrome/HKCU, environment, credentials, supervisor, schemas, historical Issue #111, UNKNOWN, Claim, consumed_at, or PR3-o are NOT authorized by this document.

## Non-goals

- No new local Bridge or independent Browser Bridge dependency; those remain separate later product routes.
- No direct smartphone connection to the Windows RCC pipe, remote command listener, IP allowlist, new token or second MCP/tunnel service.
- No new BCT Work or execution action is created to document this trust decision.

Acceptance outcome: MOBILE_ENTRY_PRESERVED_SOURCE_CONTRACT / TRUST_BOUNDARY_NARROWED_FOR_PERSONAL_DESKTOP / LIVE_UNCHANGED / SCHEMA2_OFF / HIGH_IMPACT_EXECUTION_GATE_NOT_YET_IMPLEMENTED.
