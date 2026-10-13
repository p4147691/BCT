# BCT bounded directory-tree read

Status: LIVE_ACCEPTED.

`bct_read` remains file-first by default.  A caller that needs a folder listing must
explicitly use `operation: "directory_tree"` with an absolute path in its work root.
The operation has bounded `depth` (0–6) and `limit` (1–1000), returns a deterministic
list of `file`, `directory`, `symlink`, `other`, or `unreadable` entries, and never
descends through a symlink or Windows reparse point.

Regression coverage verifies normal file reads, bounded tree output, no link traversal,
outside-work rejection, malformed bounds rejection, and authenticated MCP catalogue
behaviour. GitHub CI passed for PR #52. The deployed Core was verified by creating a
read-only work rooted at `D:\BCT` and calling `bct_read` with `directory_tree`; it returned
both file and directory entries without truncation.
