# Chrome Auto Proxy module

This directory is the Git-managed source for BCT Auto Proxy. It is a replaceable BCT module, not
BCT Core.

Baseline recovery date: 2026-10-13

Recovered without byte changes from:

- backend source: `D:\ACT\runtime\chrome-auto-proxy`
- installed extension: `D:\ACT\runtime\chrome-auto-proxy\extension`
- active unpacked extension ID: `pkjapgiipjanapbhmfoepdalgemhlpag`

The recovery deliberately excludes `private/`, `local-token.js`, `wireproxy.conf`, logs,
`__pycache__` and `wireproxy.exe`. Those are secret, generated or third-party runtime assets and
must never be committed. `BASELINE_SHA256.txt` records the exact imported public bytes.

The recovered bytes above remain recorded as provenance. The operational backend now targets
`D:\BCT\runtime\modules\chrome-auto-proxy`, and the unpacked extension is installed from
`D:\ChromeExtensions\BCT-Auto-Proxy\extension` with fixed extension ID
`belokajbbpdnchnobjmmllelhmiajikn`.

Private WireGuard configuration, the helper token and the third-party `wireproxy.exe` are deployed
as runtime assets from an exact-SHA migration receipt. They remain outside Git. The legacy ACT
runtime must not be removed until the BCT backend and extension have both passed live acceptance.
`start_proxy.cmd` is the Git-managed Windows startup entrypoint for the BCT runtime path.
