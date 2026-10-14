# BCT modules

`src/bct/core` is the small control kernel.  Everything that can be installed,
reloaded, replaced, or understood independently belongs here instead of in the
kernel.

| Module | User-facing responsibility | Runtime/installation boundary |
| --- | --- | --- |
| `bdc` | BCT Desktop Control: desktop, window and native UI automation | BCT-owned native processes; never a second policy authority |
| `rcc` | Browser conversation creation and exact-once relay control | Chrome extension + Native Messaging host |
| `monitor` | Window observation and simple window/node status | Chrome extension + Native Messaging host |
| `github` | GitHub integration and runner operations | GitHub API/Actions and bounded runner services |
| `mcp` | ChatGPT/Codex control ingress | Existing App/tunnel identity retargeted to BCT MCP |
| `status-ui` | Read-only BCT operational page | Served by the BCT runtime |

Modules use Core's work, policy, operation, receipt and conflict contracts.
They do not import ACT code or create their own ownership/policy systems.

Module source stays in the official Git repository but is not copied into the
`bct_runtime_v1` Core release. Each installable module gets its own exact
deployment boundary when it is activated. The only module asset embedded in
the Core release is the read-only `status-ui` that Core itself serves.
