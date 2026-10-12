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

The former `D:\PROJECTS\BCT` checkout is retained only as a rollback/bootstrap witness during
the source-root transition.  It is not deleted or silently updated, and new BCT work should use
`D:\BCT\source` or a worktree under `D:\BCT\worktrees`.
