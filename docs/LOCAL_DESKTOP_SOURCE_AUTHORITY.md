# Desktop-local source authority (2026-10-24)

Each owned project's desktop-local source / local Git main is canonical. GitHub is remote publication, backup, CI and review, not automatic source synchronization into the PC.

BCT source: D:/BCT/source; runtime: D:/BCT/runtime.
BCT Monitor source: D:/BCT/source/modules/monitor; installed: D:/ChromeExtensions/DesktopWindow-Monitor.
RCC source: D:/BCT/source/modules/rcc; installed: D:/ChromeExtensions/RCC.
BCT Auto Proxy and ChatGPT New Tab source: D:/BCT/source/modules.
Independent Clean Window source: D:/ChromeExtensions/CleanWindow-virtual-desktop-fix; installed: D:/ChromeExtensions/CleanWindow.
Independent VTL source: D:/AI_TOOLS/VIRTUAL-TEST-LAB.
DesktopWindow local source: D:/ChromeExtensions/DesktopWindow; remote divergence and active feature branch must be reconciled.
R+L Web Translate source: D:/ChromeExtensions/R-L-Web-Translate-D; same-dir unpacked runtime, release separation not accepted.
WIOT source: D:/ChromeExtensions/Web-Image-OCR-Translate; Git and installed extension ID pending confirmation.

Rules:
1. Preserve active jobs, exact Git branches, runtime and data. Observe source/runtime SHA before any mutation.
2. Incorporate verified installed-only changes into local source. Do not copy older source onto installed files or live files over source wholesale.
3. Source changes are tested on desktop, accepted on local main, published to GitHub fast-forward-only with exact SHA. Remote divergence means SYNC_CONFLICT; never force-push or auto-pull.
4. Runtime release requires expected source SHA and expected installed SHA, backup, atomic bounded update, verification and rollback.
5. Statuses LOCAL_POLICY_COMMITTED, SOURCE_LIVE_RECONCILED, REMOTE_PUBLISHED, LIVE_ACCEPTED are distinct. Do not imply remote workflows are disabled while local commits remain unpublished.

Audit registry: D:/BCT/data/BCT_LOCAL_CANONICAL_PROJECT_REGISTRY_20261024.json
Read-only blocker preflight: D:/BCT/data/bct_local_canonical_preflight_20261024.py
