# Chrome Auto Proxy module

This directory is the Git-managed public source baseline for the currently installed Chrome Auto
Proxy. It is a replaceable BCT module, not BCT Core.

Baseline recovery date: 2026-10-13

Recovered without byte changes from:

- backend source: `D:\ACT\runtime\chrome-auto-proxy`
- installed extension: `D:\ACT\runtime\chrome-auto-proxy\extension`
- active unpacked extension ID: `pkjapgiipjanapbhmfoepdalgemhlpag`

The recovery deliberately excludes `private/`, `local-token.js`, `wireproxy.conf`, logs,
`__pycache__` and `wireproxy.exe`. Those are secret, generated or third-party runtime assets and
must never be committed. `BASELINE_SHA256.txt` records the exact imported public bytes.

The replacement manifest uses fixed extension ID `belokajbbpdnchnobjmmllelhmiajikn`. The legacy
installed path and identity remain in service until the replacement is loaded, state is verified and
the old extension is disabled.
