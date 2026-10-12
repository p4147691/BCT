# Active DesktopWindow Monitor source

- Active Chrome extension: `D:\ChromeExtensions\DesktopWindow-Monitor\extension`
- Active Native Messaging hosts: `D:\ChromeExtensions\DesktopWindow-Monitor\native`
- Active validation tools: `D:\ChromeExtensions\DesktopWindow-Monitor\tools`
- Recovery-only history: `D:\ChromeExtensions\archive\DesktopWindow-Monitor-backup-20260922`

Do not copy or execute recovery files over the active runtime without an explicit, file-level rollback review. Historical patch scripts and backups are not implementation authority.

Monitor startup/F5 performs one explicit browser-endpoint snapshot reconciliation. It does not use periodic heartbeat expiry. Missing bridge instances are retained in ACT history as `OFFLINE` and excluded from the active node list.

The Monitor `리로드` button uses a fail-stop transaction. It parks every non-canary Monitor tab, reloads the extension once, then restores Monitor screens one at a time. A screen acknowledges success only after every desktop thumbnail has a rendered frame; the next screen is restored only after that acknowledgement. Script/load/thumbnail failure leaves the transaction stopped at that screen instead of opening the remaining screens concurrently.
