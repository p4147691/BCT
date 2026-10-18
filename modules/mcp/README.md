# BCT MCP ingress

BCT reuses the existing private ChatGPT App and OpenAI tunnel identity. The local tunnel target is
`http://127.0.0.1:18790/mcp`; creating a second App or tunnel is not part of the migration.

The tunnel supplies the exact BCT runtime token through `X-BCT-Token`. Its configuration stores a
`file:` reference to `D:\BCT\runtime\mcp.token`, never the token value. `Authorization: Bearer`
remains supported for ordinary local MCP clients. Both headers authenticate the same exact token;
neither changes the principal or capability catalogue.

The third-party tunnel-client binary is an external tool asset. It is installed under
`D:\TOOLS\OpenAI\tunnel-client`, hash-verified, and is not committed to this repository.

`ops/run_bct_tunnel_supervisor.ps1` is BCT's logon recovery entry point. It keeps the existing
private App/tunnel identity, verifies the exact executable and BCT MCP target, injects only the
file reference to the BCT token, and refuses a mismatched running target. The compatibility alias
remains `act-control` until the owning ChatGPT App display name is changed; that alias is not an
ACT runtime dependency.

The tunnel client's loopback health URL file is discovery metadata, not the tunnel process itself.
If that file is removed while the exact process remains alive, the supervisor enumerates only that
PID's loopback listeners, requires exactly one endpoint whose `/healthz` and `/readyz` return the
expected bodies, and atomically restores the configured URL file. A missing file never authorizes a
second tunnel process. An ambiguous or failed probe is logged as degraded and left for diagnosis.
Development probes must use a distinct profile directory, alias, and health URL file; reusing the
production `act-control` profile can overwrite and later delete the production discovery file even
when the production process itself remains healthy.

`ops/run_bct_core_supervisor.ps1` is the matching BCT Core recovery entry point. It loads only the
exact release named by `D:\BCT\runtime\current.json`; `bct.supervisor` verifies the immutable release,
durable service receipt, PID fingerprint and health contract before it accepts or starts the process.

`ops/BCT-Core-Supervisor.task.xml` is the user-session Task Scheduler wrapper for that exact
supervisor. It is intentionally bounded to the BCT runtime path, starts at sign-in, hides its host
window, keeps one instance, and asks Windows to restart the supervisor after an unexpected exit.
It does not launch a second BCT Core directly, does not run an arbitrary command, and retains the
supervisor's PID/fingerprint/health checks before any Core start.

`ops/BCT-Tunnel-Supervisor.task.xml` is the matching user-session recovery host for the private
tunnel. It runs only `run_bct_tunnel_supervisor.ps1` at sign-in, keeps one supervisor instance, and
uses the same bounded restart policy. The script still owns the safety decision: it validates the
exact tunnel executable, ID and MCP target before it reuses a live process or makes one connect
attempt. It never starts a second tunnel just because the health metadata is stale or absent.
The profile reader accepts UTF-8 (with or without BOM), UTF-16, and a legacy Windows ANSI profile,
then normalizes a changed profile to UTF-8. This prevents Windows PowerShell 5.1 from corrupting a
non-ASCII Windows user-profile path before comparing the configured health URL file.

