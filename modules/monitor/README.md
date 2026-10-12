# BCT Monitor module

This is the BCT-owned source for DesktopWindow Monitor. The installed payload remains at
`D:\ChromeExtensions\DesktopWindow-Monitor` until an exact bounded deployment is accepted.

- `extension`: Chrome UI and observation payload
- `native`: Native Messaging manifests and host source
- `tools`: validation and bounded publication

Monitor owns observation, exact window controls, and a simple window/node/status projection. It
does not own identity, roles, work, policy, or operation receipts; those belong to BCT Core.

The imported baseline still contains a frozen compatibility UI for the former ACT organization
model. No new BCT feature may depend on it. It is retired separately with focused Monitor tests so
that window observation is not damaged by a source-layout change.
