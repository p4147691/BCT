# BCT modules

`src/bct/core` is the small control kernel.  Everything that can be installed,
reloaded, replaced, or understood independently belongs here instead of in the
kernel.

| Module | User-facing responsibility | Runtime/installation boundary |
| --- | --- | --- |
| `bdc` | BCT Desktop Control: desktop, window and native UI automation | BCT-owned native processes; never a second policy authority |
| `rcc` | Browser conversation creation and exact-once relay control | Chrome extension + Native Messaging host |
| `monitor` | Window observation and simple window/node status | Chrome extension + Native Messaging host |
| `decision` | Optional local decision-model recommendation | Local model endpoint; deterministic policy remains in Core |
| `github` | GitHub integration and runner operations | GitHub API/Actions and bounded runner services |
| `status-ui` | Read-only BCT operational page | Served by the BCT runtime |

Modules use Core's work, policy, operation, receipt and conflict contracts.
They do not import ACT code or create their own ownership/policy systems.

