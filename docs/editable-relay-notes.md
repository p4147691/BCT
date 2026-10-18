# Editable AI relay reminders

Once this code is deployed, edit optional UTF-8 plain-text files:
- D:/BCT/runtime/config/manager-relay-note.txt (Manager Wake V2)
- D:/BCT/runtime/config/worker-relay-note.txt (Worker assignment)

Create the config folder and file as needed. Missing file uses the built-in default reminder.
New messages read the file on every invocation; editing requires no CI, GitHub PR, merge, restart or deployment.
Previously sent messages are never altered. Limit: 2,000 characters / 4 KiB, without BCT envelope delimiters.
These reminders do not grant actions or change the JSON protocol. Manager and Worker make work decisions.
The first deployment of this feature itself still needs the normal release process.
