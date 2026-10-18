# BCT Project Memory Continuity V2 — read-only handoff

Status: ISOLATED CANDIDATE ONLY. Not currently LIVE. No RCC or Chrome effects.

## Goal, authority and limitations

The AI Manager decides what evidence means, which work to delegate, what to
finish, and when to update the project ledger. Project Memory only persists
Manager-authored summaries and links to existing source records. The project
group is advisory context, never a BCT permission or automatic instruction.

This slice integrates the existing Project Memory V1 file store with the
existing Orchestration status output. There are no new tables, Worker RESULT
fields, Manager Decision V1 fields, RCC transport actions, or Wake changes.

## Read-only Manager continuity

When the service has a configured data_root, it looks under
data_root/project-memory. The normal Orchestration status call first checks
the exact Work/Session and then reads ledgers explicitly linked to that Work
or Session. If linked, output.project_memory.status is READ_ONLY with bounded
Manager-authored context and verifiable original BCT source event metadata.
If absent, output remains unchanged. If corrupted or manager epoch changed,
status remains available but context is UNVERIFIED.

Existing Manager Wake V1/V2 already tells a Manager to inspect Orchestration
status before deciding. Consequently the Manager can review this continuity
data on wake using its existing authorized status call. Wake and Worker
protocols remain byte-for-byte unchanged: RCC submit ACK is not a Manager
decision ACK.

## Verified source and pagination contract

- Source truth: existing Work, Session, Assignment, Mailbox, Manager Decision,
  outbox, and Event records; this code does not duplicate their payloads.
- Related events: event_id, kind, subject_id, created_at only. The source
  selectors are verified using original SQLite Work and Session bindings,
  never untrusted IDs from ledger links.
- BCT SQLite is opened read-only with query_only=ON.
- Maximum four linked projects and at most 50 related events per project by
  default, with a 100-event cap per explicit reader call.
- Maximum 1000 source IDs; incomplete coverage is explicitly indicated by
  source_complete=false and an incomplete reason.
- Maximum 40 assignment metadata items, eight Manager decisions, eight next
  actions and bounded text fields; truncation sets bounded=true.
- delta.observed_through is an advisory proposal, not an automatic cursor
  commit. The Manager may advance the V1 ledger cursor ONLY after reviewing
  evidence. A source event highwater does not imply all BCT events were read.
- External links such as GitHub and ChatGPT remain unverified until their
  corresponding original sources are read. They are never an authority grant.
- Source Work assignment epoch and current manager epoch are checked.
- A related but foreign Work in project links never widens source event access.

The Manager's project-level comprehensive review and ability to issue new
Worker instructions must use the unchanged authorized orchestration flow.
No AI decision engine is implemented by BCT.

## Follow-on acceptance

1. Use only temporary SQLite and file roots, including a fake relay that
   refuses any send, to verify status context and pagination.
2. Independent code review, draft PR and CI before separate merge approval.
3. After a separately approved LIVE release, prove a new isolated project
   context readback and Manager Wake status, without old UNKNOWN redelivery.
4. Only then conduct a fresh real AI Manager/Worker E2E with exact verified
   browser identities and user-authorized targets.

Focused isolated tests:
PYTHONPATH=src python -m unittest discover -s tests -p test_project_memory_context.py -v
