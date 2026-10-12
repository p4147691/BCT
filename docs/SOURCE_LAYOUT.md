# BCT local package layout

The user-facing BCT package is rooted at `D:\BCT`.

| Path | Purpose |
| --- | --- |
| `D:\BCT\source` | Clean local `main` checkout synchronized from GitHub |
| `D:\BCT\worktrees` | Isolated feature and fix worktrees |
| `D:\BCT\runtime` | Immutable releases, active pointer, service and deployment receipts |
| `D:\BCT\data` | Operation database, process sessions, decision endpoint and acceptance evidence |
| `D:\BCT\models` | Large local model assets kept outside Git |
| `D:\BCT\local-llm` | BCT-owned model runtime dependencies |

GitHub `main` remains the source authority.  The local source checkout must be clean and at the
exact verified main SHA before deployment.  Runtime files are never edited in place.

The former `D:\PROJECTS\BCT` checkout and its linked worktrees are archived under
`D:\Archive\BCT-Bootstrap-20261013` with verified ZIP and Git-bundle evidence.  The only active
source checkout is `D:\BCT\source`; new isolated work belongs under `D:\BCT\worktrees`.
