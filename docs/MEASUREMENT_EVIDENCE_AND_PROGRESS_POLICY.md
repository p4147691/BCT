# BCT measurement evidence, progress, and action policy

**Current canonical interpretation:** This policy supplements the root `AGENTS.md`. It overrides contradictory procedural wording in older design notes, active plans, or archived incident reports. It does not rewrite historical Operation receipts.

## Purpose
BCT measurement exists for operator visibility and troubleshooting. It is **not a permission gate**, work ownership, claim, lock, or evidence of failure merely because it returned no result.

## Evidence standard
1. A measurement may influence a factual decision only if its source, exact target and session, collection method, collection time/freshness, integrity, and outcome can be corroborated. Otherwise classify it `MEASUREMENT_UNVERIFIED`; treat the output as advisory only. Do not infer target state, absence, failure, unauthorized access, or success.
2. Never reserve a resource Claim, leave a blocking Claim, freeze a Work, quarantine a node, withhold unrelated tasks, or block repair because a measurement, status probe, health poll, readiness observation, CI read, Monitor cache, or instrumentation is missing, stale, delayed, timed out, or internally inconsistent. Fix the observation pipeline separately.
3. Continue independent work, diagnosis, repair, testing, and replacement observations. Report the source defect and owner as a concrete fix task, not a terminal `BLOCKED/UNKNOWN` conclusion. An ordinary observation can be remeasured with a new *observation* ID because it has no external effect.
4. BCT's historical `UNKNOWN` receipt remains an audit event, not a global stop signal or permission to assert that an external action took place. Existing receipts are not mass rewritten and unresolved counter values must not be promoted to active locks.
5. An actual state-changing action (file delete, deployment, process stop, release, irreversible overwrite, money/credentials, etc.) is a separate category. Require authenticated user/Work scope, exact target and action, explicit approval for high-risk effects, and capability-specific execution evidence. Never replay a possibly executed destructive effect solely because its return receipt was lost. This **effect-specific** constraint is not an instrumentation Claim and may not prevent unrelated diagnostic/repair work.

## Normal messages and duplicates
- Ordinary ChatGPT messages and work deliveries are recoverable communication, not destructive changes. Delivery transport should expose message identity and optional duplicate indicator; the receiving node decides how to interpret duplicate or repeated content. Duplicated ordinary messages are not a reason to stop the entire workflow.
- Preserve the original text/operation receipt when available. Do not auto-cascade identical replay attempts during unknown transport effects; use an explicit recipient-visible duplicate marker or one sender decision, and keep exact operation IDs for tracking.
- Escalate *only genuinely high-impact commands* to explicit human approval with target/impact and proof. Unproven measurement by itself is never such a command.

## Operational responsibilities
- If results cannot be trusted: label the measurement invalid, locate the faulty adapter, provider, timing, stale cache, missing ACK, or contract mismatch, fix it, and continue with other valid evidence.
- Distinguish `MEASUREMENT_UNVERIFIED`, `ACTION_NOT_APPLIED`, `ACTION_APPLIED`, and `ACTION_REVIEW_REQUIRED` in user-facing text. Never use a vague `UNKNOWN` to terminate investigation.
- A measured count, time, or recent status is only an observation. Unrelated execution stays available without a measurement receipt.
- Old design/incident documents remain historical evidence. When they say UNKNOWN/Claim globally blocks work, this current document and root `AGENTS.md` supersede that *operating instruction*. The old receipt is never falsified.

## Verification
- Prove measurements allocate **zero** resource Claim rows, including at operation start and after a measurement timeout.
- Prove old UNKNOWN rows do not block fresh unrelated Work and their audit histories remain immutable.
- Prove a second normal message is visible as a duplicate to a receiving node without automatically halting unrelated work.
- Prove dangerous operations still require exact scope, required approval, and no blind automatic replay.
- Prove no changes to running Chrome, RCC, Core, or live DB during isolated development.
