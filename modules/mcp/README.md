# BCT MCP ingress

BCT reuses the existing private ChatGPT App and OpenAI tunnel identity. The local tunnel target is
`http://127.0.0.1:18790/mcp`; creating a second App or tunnel is not part of the migration.

The tunnel supplies the exact BCT runtime token through `X-BCT-Token`. Its configuration stores a
`file:` reference to `D:\BCT\runtime\mcp.token`, never the token value. `Authorization: Bearer`
remains supported for ordinary local MCP clients. Both headers authenticate the same exact token;
neither changes the principal or capability catalogue.

The third-party tunnel-client binary is an external tool asset. It is installed under
`D:\TOOLS\OpenAI\tunnel-client`, hash-verified, and is not committed to this repository.

