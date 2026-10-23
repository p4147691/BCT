# Legacy orchestration relay reminders

The following optional Windows text files are retained for older Orchestration
callers that still invoke `_relay_note()`:
- D:/BCT/runtime/config/manager-relay-note.txt (Manager Wake V2)
- D:/BCT/runtime/config/worker-relay-note.txt (Worker assignment)

Create the config folder and file as needed. Missing file uses the built-in default reminder.
New messages read the file on every invocation; editing requires no CI, GitHub PR, merge, restart or deployment.
Previously sent messages are never altered. Encoding: UTF-8 (with or without BOM), UTF-16 LE/BE with BOM (Windows Notepad 'Unicode'), UTF-32 with BOM, and Korean ANSI/CP949 when UTF-8 decoding fails. The encoding is detected each time a new message is created. No conversion or restart is needed. Files without a BOM should use UTF-8 or CP949. Limit: 2,000 characters / 8 KiB, without BCT envelope delimiters.
These files are **not** automatically injected into the canonical Delivery
Ledger Worker message or Manager return. That path has one message setting
source: `D:/BCT/runtime/config/relay-message-settings.json`. Move any wording
that the current path still needs into its `worker_additional_instruction` or
`manager_additional_instruction` field. This separation prevents an old note
from silently restoring superseded message semantics.

The legacy reminders do not grant actions or change the JSON protocol. They
must not be treated as the current relay design merely because an older caller
still reads them.
