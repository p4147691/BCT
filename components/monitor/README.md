# DesktopWindow Monitor Runtime

Monitor 작업의 첫 진입점은 `extension\AGENTS.md`이고, canonical local structure map은 `extension\MONITOR_STRUCTURE.md`다.

- active browser payload: `extension\`
- native manifest/source/runtime: `native\`
- operational tools: `tools\`
- history only: `backup\` (inactive Native builds는 `backup\native-history\`)

Authority를 폴더 이름이나 오래된 worktree에서 추측하지 말고 `extension\MONITOR_STRUCTURE.md`의 확인 순서를 따른다.
