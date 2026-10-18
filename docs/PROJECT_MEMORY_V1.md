# BCT Project Memory V1 — minimal durable ledger

Status: isolated source/test candidate only; no BCT LIVE deployment, RCC send,
manager Wake change, new SQLite table, or manager decision envelope change.

## Purpose and responsibility

AI Manager chooses project scope, conclusions, next tasks, and worker
instructions. BCT Project Memory persists the Manager's summary and exact
source references, not the original Worker/result/conversation data.
Project is an advisory grouping, not a BCT Work execution boundary.
One node, Work, or Session may participate in multiple project contexts.

## Existing BCT contracts reused without modification

- Work/Session: existing IDs, objectives, states, plan revision, manager epoch.
- Assignment/Mailbox: original instructions and structured RESULT evidence.
- Manager Decision/Outbox: decisions about individual result events only; no
  project-level decision is invented in COMPLETE/FOLLOW_UP envelope.
- Event: time-ordered technical events. Monitor is a bounded projection,
  NOT a completeness-guaranteed historical event reader.
- GitHub Issue/PR and ChatGPT: references only; existence and content must
  be checked using actual source before treating a claim as verified.
- Existing FileRead/FileWrite capabilities: expected SHA read/write and BCT
  operation receipts. A file hash check is not itself a cross-process ledger
  transaction.

Project Memory V1 adds a standalone Python library and CLI, and one
file-list entry in bct.toml's deployment profile so a future approved release
actually includes the module. It adds no new MCP tool, changes no runtime
registration, emits no automatic Wake and sends no Worker message. It is not
available to LIVE until a separately approved exact-SHA deployment.

## Proposed on-disk layout

Root explicitly chosen by operator, e.g. D:\BCT\data\project-memory.
This candidate DOES NOT create or modify this LIVE location.

    <root>\
      subtitle-auto\
        .ledger.lock
        current.json
        revisions\
          00000001-<full_sha256>.json
          00000002-<full_sha256>.json
      bct-durable-collaboration\
        ...

Project ID is a stable lowercase slug ([a-z0-9][a-z0-9-]{0,63}),
independent of display title and changing project scope.

current.json pointer fields:
schema, project_id, revision, revision_file, sha256.
An immutable revision: schema, project_id, revision, previous_sha256,
author, created_at (UTC ISO 8601), record. Parent revisions are verified by hash from CURRENT.

Record example (AI-authored data, not an executable instruction):

    {
      "title": "자막 생성",
      "goal": "음성 인식과 OCR 통합 완성",
      "scope_note": "그룹은 협업 맥락, 제약이 아님",
      "summary": "AI 매니저가 작성한 현재 진행 상황",
      "links": [{"type": "bct_session", "id": "session-id"}],
      "items": [
        {"text": "Worker B 결과를 검토한다",
         "evidence": [{"type": "bct_result", "id": "result-message-id"}]}
      ],
      "decisions": [{"text": "이전 구현은 반복하지 않는다", "evidence": []}],
      "next_actions": [{"text": "결과 원본 확인", "evidence": []}],
      "checkpoints": {"bct_event_id": 0, "external": {}}
    }

Records are bounded to 256 KiB. Do not duplicate a long chat or arbitrary
RESULT text in the record. A reference does NOT guarantee that a different
AI node can read the content. Before acting, the AI must distinguish
MERGED, APPLIED, UNKNOWN, and NOT_VERIFIED using original evidence.

## Public APIs and CLI

- ProjectMemoryStore(root).get(project_id): verify current snapshot or None.
- .save(project_id, expected_revision=n, author=..., record=...):
  serialized writer, CAS revision, immutable history; identical current
  content returns duplicate=True.
- .history(project_id): verify parent chain back to genesis, ignoring orphans.
- .projects(): list known project slugs with current pointers.

CLI after setting the src Python path:

    python -m bct.core.project_memory --root ROOT list
    python -m bct.core.project_memory --root ROOT get subtitle-auto
    python -m bct.core.project_memory --root ROOT history subtitle-auto
    python -m bct.core.project_memory --root ROOT put subtitle-auto --input record.json --expected-revision 0 --author manager-a

Output JSON uses ASCII escaping for Windows console portability.
No record bodies are sent to passive monitor/telemetry. CLI get/history
returns record contents ONLY when intentionally requested.

## Safety, history and crash behavior

Project-local OS file lock serializes writers across independent processes.
Inside lock: read pointer, check expected revision, fsync a temporary revision,
atomically publish its complete bytes, then atomically replace current pointer. Reader can see previous or new
committed pointer, never a partially written current pointer. SHA256 confirms
the committed revision. Previous committed snapshots are never overwritten.

If failure occurs before current replacement, the former committed revision
remains authoritative, and orphaned revision files are NOT treated as history.
Corrupt pointer or committed revision produces an error rather than falling
back or silently fixing it. Stale expected revision must re-read and let AI
reconcile a new proposal.

Source bookmark bct_event_id is monotonic by ledger update. This is only
a Manager observation checkpoint, not a guarantee that ALL BCT events were
retrieved. Advance only after actually reviewing included evidence.
No event scanner/delta query/automatic Wake/GitHub polling is implemented V1.

Project group labels do not restrict work capabilities. Existing BCT
assignment, Claim/UNKNOWN and RCC idempotency protections are untouched.

## Follow-up boundaries

Later steps may add stable historical event cursor reads, verified source
deltas, manager wake context, and an independent project-wide review trigger.
They must not be conflated with a Worker RESULT consumption ACK and must not
rewrite the existing Manager Decision V1 envelope.

Focused Windows tests:
PYTHONPATH=src python -m unittest discover -s tests -p test_project_memory.py -v

Use temporary test roots only; NO original Work/Session/Claim/RCC mutation.

