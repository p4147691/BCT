# Editable AI relay reminders

Once this code is deployed, edit optional Windows text files:
- D:/BCT/runtime/config/manager-relay-note.txt (Manager Wake V2)
- D:/BCT/runtime/config/worker-relay-note.txt (Worker assignment)

Create the config folder and file as needed. Missing file uses the built-in default reminder.
New messages read the file on every invocation; editing requires no CI, GitHub PR, merge, restart or deployment.
Previously sent messages are never altered. Encoding: UTF-8 (with or without BOM), UTF-16 LE/BE with BOM (Windows Notepad 'Unicode'), UTF-32 with BOM, and Korean ANSI/CP949 when UTF-8 decoding fails. The encoding is detected each time a new message is created. No conversion or restart is needed. Files without a BOM should use UTF-8 or CP949. Limit: 2,000 characters / 8 KiB, without BCT envelope delimiters.
These reminders do not grant actions or change the JSON protocol. Manager and Worker make work decisions.
The first deployment of this feature itself still needs the normal release process.
