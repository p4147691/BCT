# BCT chat continuity: replace tabs, preserve project state

**Priority:** continue the project, not the exact ChatGPT tab identity.

1. Read BCT status, exact RCC result/presence, and BCT-owned tab state.
   A missing tab or failed receipt is NOT proof a message was unsent.
2. Check progress, **not send again**. After two real observations and
   at least 90 seconds without progress in a BCT-owned dedicated chat,
   switch to a fresh separate chat. User-active/personal tabs are left alone.
3. Retire exactly one old finished/UNKNOWN RCC instance-global Claim if it
   blocks independent work. Use the bct.chat_continuity CLI to assess by
   default; --apply for the exact observed stuck case. The old BCT operation
   outcome, digest and all other Claim rows remain unchanged. The new audit
   event states ABANDONED_UNVERIFIED, **never NOT_APPLIED**.
4. Close only a demonstrably BCT-owned tab that is not used by a person.
   Closing is optional. Never close an unrelated Chrome process.
5. Start a NEW chat with a NEW Work/Operation ID as appropriate. Hand over
   project goal, latest BCT Project Memory, verified results, unresolved
   UNKNOWN notes and next steps. Do not resend an old uncertain operation.
6. If the old chat later reappears, use its evidence without reinstating
   its manager/worker execution authority automatically.
7. Continue independent work even if one operation remains uncertain.

The checks count separate state/UI/receipt observations, NOT retries of
the same send. The original effect cannot be asserted NOT_APPLIED merely
because the old tab did not visibly react.

Read-only plan:

    python -m bct.chat_continuity --db <state.sqlite> \
      --original-work <work-id> --original-operation <op-id> \
      --instance-id <id> --checks 2 --no-progress-seconds 120 \
      --reason "Dedicated BCT chat stalled" --bct-owned

Add --apply only after checking the observed values. The helper is limited
to one historical broad RCC send Claim and does NOT operate on Worker
assignments, other Claims, user browser tabs or UNKNOWN receipts.
