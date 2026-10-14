# BCT Monitor module

This is the BCT-owned source for DesktopWindow Monitor. The installed payload remains at
`D:\ChromeExtensions\DesktopWindow-Monitor` until an exact bounded deployment is accepted.

- `extension`: Chrome UI and observation payload
- `native`: Native Messaging manifests and host source
- `tools`: validation and bounded publication

Monitor owns observation, exact window controls, and a simple window/node/status projection. It
does not own identity, roles, work, policy, or operation receipts; those belong to BCT Core.

The imported baseline still contains a frozen compatibility UI for the former ACT organization
model. No new BCT feature may depend on it. The BCT 2.0 surface hides that compatibility UI and
keeps physical window/desktop/thumbnail behavior independent of node or organization metadata.

The primary Monitor header exposes only live, explicit boundaries: BCT health/status
through the BCT status view, and installed-extension reload. Its main panel shows a read-only,
BCT-native summary of RCC-observed ChatGPT windows/tabs using exact Chrome window and tab IDs; it
does not revive the former ACT organization authority. Reload reads the installed payload again;
it is not source integration or deployment. The retired Local LLM UI on port 7865 is not presented
as a working feature.
