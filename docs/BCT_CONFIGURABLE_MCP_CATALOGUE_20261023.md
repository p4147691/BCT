# BCT MCP 도구 목록 설정화 — 격리 구현 1차

## 목적
운영 BCT의 MCP 도구 목록(표시·숨김·설명)을 매번 main 소스 수정 없이 제어한다. 기존 BCT Work/Operation/Policy 권한, 영수증, CDP 기본 경로를 유지한다.

## 구현된 범위
- `src/bct/mcp_catalogue_config.py`: FastMCP 정식 등록 도구만 TOML로 노출·숨김·설명 변경. 임의 기능 등록 금지. 필수 도구 숨김 금지. 유효하지 않은 파일은 마지막 정상 목록 보존 및 `bct_capabilities.catalogue_warning`으로 보고.
- 실제 MCP `tools/list`를 호출할 때 설정을 다시 읽음. 동일 MCP 세션에서 목록 새로고침으로 변경 적용; 운영 MCP 서버 재시작·메인 변경 불필요(최초 기능 배포 이후).
- `src/bct/features/browser_extension_manage.py`: `inventory` / `pages` **읽기 전용**. 기존 BCT CDP 연결 관리자를 재사용. `create/update/remove/evaluate_script`는 이 공통 도구에서는 아직 차단.
- `cdp_connection.py`: 공식 Chrome DevTools MCP의 `list_extensions` 읽기만 추가 허용. 임의 JS eval, 탭 변경은 여전히 차단.
- `service.py`: 설정 파일 경로는 BCT runtime data_root의 `mcp_tools.toml`. 파일이 없으면 기존 목록 그대로.
- `bct.toml`: 새 capability 기본 등록 및 배포 아티팩트에 파일 2개 포함. 운영 Chrome CDP가 설정되지 않은 상태에서는 이 도구도 연결되지 않는다.
- `docs/mcp_tools.example.toml`: 운영 설정 파일 예시.

## 조회 방식
등록/배포된 BCT 노드에서 MCP `tools/list`를 새로고침하면 `bct_browser_extension_manage`를 발견한다.
BCT Work 생성 actions=[`browser_extension_manage`] 후 `bct_browser_extension_manage(work_id, operation_id, arguments={operation: inventory})`로 조회.
`inventory`는 DevTools MCP에서 관측된 확장 목록으로, 모든 Web Store 확장의 완전한 목록이라고 보장하지 않는다.

## 현재 미구현
- 검증 완료된 Tampermonkey CDP CRUD 실행기를 이 공통 capability의 쓰기 경로에 연결하는 작업
- MCP notifications/tools/list_changed의 자동 push (현재는 사용자가 도구 새로고침을 호출하면 반영)
- Chrome CDP manager의 운영 프로필 명시적 opt-in (기본 bct.toml [cdp] enabled=false)
- 운영 core 배포와 실제 외부 ChatGPT/Codex 도구 새로고침 수락시험

## 시험과 게이트
- 신규 config 직접·MCP in-memory client tools/list 갱신 시험 PASS
- 기존 CDP 관리 테스트 PASS
- 새 도구의 쓰기 명령은 prepare 단계에서 거부되는 테스트 PASS
- 실제 HTTP 격리 서버 readiness 시험은 *미변경 main에서도 동일한 SERVICE_READINESS_TIMEOUT*이 발생. 원인 분리 없이 PASS 처리 금지.
- src/main과 운영 Chrome·RCC·Tampermonkey 기존 스크립트 변경 금지. 이번 코드는 격리 Worktree에서만 수정.

## 이후
1. CDP 연결을 BCT 정책에 안전하게 opt-in하고 inventory 기능 실제 MCP call E2E
2. 기존 운영 PASS 코드를 Work·Operation으로 감싼 Tampermonkey CRUD 어댑터 구현. 임의 eval 도구 금지.
3. 독립 테스트 / HTTP integration / 검증된 SHA 확인
4. 로컬 main 반영 → 배포 → 서버 tools/list와 실제 클라이언트 도구 새로고침 대조. 운영 Chrome·RCC 보존
