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

`ops/run_bct_core_supervisor.ps1` is the matching BCT Core recovery entry point. It loads only the
exact release named by `D:\BCT\runtime\current.json`; `bct.supervisor` verifies the immutable release,
durable service receipt, PID fingerprint and health contract before it accepts or starts the process.

