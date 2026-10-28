# Explorer folder-open stabilization — N68 review
Date: 2026-10-28. Status: PARTIAL / NOT READY FOR MERGE.

## Verified baseline
- BCT Core generation 234, release 9f85508aa63576766cee42fd4b9a3e2f72bce6e7, status OK.
- Local main snapshot b297083791156e5510cbb9ee7359a9a358e73aaa was clean at inspection.
- Existing Explorer semantic targeting is implemented by DesktopApplicationTargetFeature (src/bct/features/desktop_session.py), with absolute existing folder resolution, Explorer-only selector, exact window binding and fail-closed ambiguity.
- DesktopProgramLaunchFeature is generic and verifies the launched process/visible-window identity. Windows Explorer may delegate window creation to an existing process, so process PID exit or lack of a window on that PID is not sufficient to declare the folder wasn't opened.
- Baseline: python -m unittest tests.test_desktop_session -q => 54 tests PASS.
- Prior request receipts indicate folder launch and actual Explorer window observation succeeded. This review did NOT reopen folders or manipulate focus.

## Proposed minimal implementation, not yet executed
1. Maintain existing desktop_program_launch API/contract for generic .exe launches.
2. Add a narrowly scoped Explorer-folder orchestration flow reusing existing semantic target list/bind, session lease, program launch, window activate/manage and lease release.
3. Validate folder strictly as existing absolute directory, refuse mutation, ensure exact folder matching (not title or PID), do not accept multiple/truncated matches.
4. Before launch, use folder semantic target to reuse one exact existing Explorer HWND; otherwise launch explorer.exe with folder argument.
5. After launch, reconcile by exact Shell folder-path lookup rather than the new process PID; handle delayed window/delegated Explorer process without retrying UNKNOWN effects.
6. Foreground only exact leased window when requested and on current virtual desktop, otherwise leave focus unchanged. Release lease in finally and report release failures separately.
7. Regression matrix: new folder, pre-opened folder, PID exits but Explorer window exists, ambiguous same path, folder absent, other desktop, minimized window, launch UNKNOWN, foreground rejection, release failure.
8. Only after implementation: focused/full regression, independent CI, supervisor merge/live E2E.

## Ownership and safety
Branch feature/explorer-folder-open-n68-20261028 at D:\BCT\worktrees\explorer-folder-open-n68-20261028.
No main merge, live deployment, restart, UI automation or actual Explorer launch performed.
No source-code patch is claimed; this is a bounded review and regression baseline, NOT a feature completion.

## Follow-up implementation checkpoint
- Added pure decision helper src/bct/integrations/explorer_folder_open.py.
- Added 10 focused decision tests, PASS (using explicit isolated src import path).
- Existing desktop session 54 tests PASS.
- Helper deliberately does not execute OS side effects or alter existing public API.
- Still missing: authorized orchestration wiring for launch/bind/activate/release, physical E2E, full suite and GitHub CI. Do not merge as complete.
