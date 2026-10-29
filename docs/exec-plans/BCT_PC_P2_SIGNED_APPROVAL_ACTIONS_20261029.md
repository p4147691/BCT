# P2 승인형 파일·프로세스 효과 — 격리 개발 검증 기록 (2026-10-29)

## 기반과 격리
- PR #347 \`feature/pc-safe-action-plans-20261029\` 후속 커밋이며, #346은 별도 OPEN PR로 유지. 두 PR의 공통 서비스/MCP 등록 파일은 감독관이 최신 main에서 충돌·중복을 검토.
- main 병합, LIVE 배포, 운영 파일/프로세스 조작, node-sync 변경 전혀 없음.
- 기존 \`FileActionPlanFeature\`, \`ProcessSessionFeature._owned_receipt\`, \`OperationCoordinator\`와 BCT Work/Operation 영수증을 재사용.

## 승인 서명·검증 경계
- \`src/bct/core/approval.py\`: pinned Ed25519 공개키로 검증하는 외부 사용자 승인 토큰.
- 정확한 principal ID, Work ID, Operation ID, capability, target, 원본 정규화 요청 SHA-256, 사용자 확인, issued/expires(최대 10분), nonce(128비트)에 바인딩.
- SQLite 트랜잭션에 nonce 해시를 **효과 발생 전 단 1회 소비**. 동일 Operation 복구는 소비 영수증의 정확한 Work·사용자·요청 해시를 확인.
- 이미 실행된 Operation은 기존 BCT 영수증으로 중복 실행 방지. 승인만 있거나 잘못된 토큰은 권한이 되지 않음.
- \`file_action_apply\`, \`process_stop_apply\`는 **approval_actions 전용**. normal_actions로 잘못 등록하면 아예 차단.
- 일반 BCT/MCP에는 승인 발급·비밀키 생성 API 없음. 서명은 별도로 인증된 실제 사용자 UI에서만 이루어져야 함.
- **현재 운영 기본 설정 \`approval_verifier.enabled=false\`이며 사용 가능한 외부 승인 서명 UI가 아직 연결되지 않음.** 따라서 현재 구현을 곧바로 LIVE로 활성화할 수 없음. 실사용 승인 연결 전 \`READY_FOR_MERGE\` 또는 운영 사용 가능으로 선언 금지.

## 파일 작업
- \`file_action_apply\`: \`move\`, \`recoverable_delete\`(격리 경로 이동), \`restore\`. 영구 삭제, 재귀/대량 삭제, 덮어쓰기, 다른 볼륨 이동 금지.
- 기존 preview의 SHA-256/size/inode/mtime 기반 계획 해시를 **효과 직전** 재검증.
- 같은 Work roots, 지정된 보호경로 제외, 원본/대상 재분석 지점 확인, 대상 점유 시 차단.
- Windows 전용 no-overwrite rename, 실행 후 대상 해시·원본 부재 확인, 불명확한 효과는 UNKNOWN 및 자동 재실행 금지.
- 복원은 별도의 사용자 서명과 신규 승인 Operation이 있어야 가능. 별도의 영구 삭제 기능은 없음.
- 경로 정규화·사전 효과 검증과 불변 요청 신원 계산을 분리하여, 이동 후 동일 Operation ID 재요청에서 원본 부재를 실패로 오판하지 않음.

## 프로세스 작업
- \`process_stop_apply\`: 기존 \`process_session\` 영수증의 Work 소유권 및 PID/생성 표식/실행 파일 지문이 필요.
- 동일 Windows 사용자·세션, 현재 Core 부모/자기 프로세스·BCT·Chrome·RCC·Monitor·Runner·Code·OS 보호 경로 제외, 자식 프로세스 존재 시 차단.
- \`graceful\`: 정확한 소유 GUI 창에 WM_CLOSE만 요청. GUI 창 없는 작업은 강제 종료로 바꾸지 않고 NOT_APPLIED.
- \`force\`: **별도 mode=force가 포함된 정확한 서명 사용자 승인 토큰** 필요. 대상 프로세스/자식/지문을 재확인한 후에만 종료.
- 프로그램 종료는 되돌릴 수 없고, 강제 종료는 운영 기본 비활성. 자동 강제 종료·광역 PID 종료 없음.

## 현재 검증과 남은 조건
- 신규 승인/효과 테스트: 20 PASS. 승인/무승인/만료/변조/범위 변경/중복/복원/충돌/변경/UNKNOWN/재개/작업자 보호/별도로 생성한 임시 프로세스 대상 강제 종료를 테스트.
- 기존 P2 계획 17, Core 17, ProcessSession 3, MCP catalogue 8, import closure, 모듈 구조, 격리 MCP 통합 시험.
- **외부 사용자 승인 서명 UI 미구현**, 실제 사용자 승인 E2E 미실행. 사용 전 신뢰된 승인 발급자 별도 준비·키 등록·사용자 확인/거부 실사용 시험 및 위협모델 검토 필요.
- 마지막 CI PASS와 PR HEAD를 대조하여 감독관에게 인계. 메인 병합·정확한 LIVE·실사용 E2E는 감독관 전담.
