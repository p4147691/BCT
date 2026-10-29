# PR #347 — 일반 로컬 모드 / 선택형 고보안 모드 설계·인계 (2026-10-29)

## 정본과 보호
- 기존 PR #347 / HEAD \`751acf10cda40217c65d529a4846283ae3933e30\` 후속 격리 개발. #346은 별도 OPEN PR로서 중복 구현하지 않는다.
- 일반 모드는 고보안 \`file_action_apply\` / \`process_stop_apply\` 및 \`ApprovalVerifier\`를 수정하거나 비활성화하지 않는다.
- main 병합, LIVE 배포, 운영 계정/ACL/DB 변경, 운영 파일 삭제, 운영 프로세스 종료, node-sync/Chrome/RCC 조작 금지.

## 사용성 정책

| 사용자가 말하는 작업 | 일반 모드(Work + Operation + 영수증) | 고보안 모드 |
|---|---|---|
| 파일 이동 | \`file_local_action(move)\` — 추가 서명 없음, Work-scoped exact path와 SHA/무덮어쓰기 | \`file_action_apply(move)\` — 기존 Ed25519 |
| 같은 폴더 내 파일 이름 변경 | \`file_local_action(rename)\` — 새 이름을 정확한 경로로 지정 | 기존 승인형 이동 |
| 파일 복구 | \`file_local_action(restore)\` — 정확한 원본/복원 위치로 이동, 덮어쓰기 없음 | 기존 \`file_action_apply(restore)\` |
| 복구 가능한 삭제 | \`file_local_action(recoverable_delete)\` — 지정한 파일을 \`.bct-recovery\` 하위로만 이동; **Windows 대화상자 YES 필수**, NO/시간 초과/비대화형은 NOT_APPLIED | 기존 승인형 \`recoverable_delete\` |
| 정상 프로그램 종료 | \`process_local_stop\` — 기존 \`process_session.start\` 원본 성공 영수증 + PID/실행 파일/생성 시각/사용자·세션 일치, GUI WM_CLOSE 정상 종료만; 강제 종료 없음 | \`process_stop_apply\` 별도 승인 |
| 영구 삭제·보호 경로·운영 서비스 종료 | 일반 모드 지원하지 않음 | 별도 강화 정책/승인/보호 검토 필요. 기존 고보안도 보호 경로 삭제와 임의 운영 프로세스 종료를 허용하지 않음 |

- 일반 모드는 기존 BCT Work 액션 \`file_local_action\` 또는 \`process_local_stop\`가 실제 사용자 지정 Work 안에 명시돼 있어야 하고, 정확한 Operation 영수증을 재사용한다. 단순 자연어만으로 파일의 Work scope를 확대하지 않는다.
- 파일 원본과 대상은 Work 경계, reparse/symlink, 보호 디렉터리(Windows/Program Files/BCT), 충돌, 원본 SHA 및 타임스탬프, 동일 볼륨과 64MiB 상한을 검사. 덮어쓰기·재귀 변경 없음.
- 정상 이동·이름 변경·복원은 사용자 요청 자체가 기존 Work 권한임을 확인하고 서명 팝업을 추가하지 않는다.
- 복구 삭제는 **호출하는 BCT Core 프로세스가 화면을 표시할 수 있는 같은 사용자 Windows 세션**에서만 GUI 확인이 보인다. 헤드리스/Session 0에서는 자동 승인하지 않고 실패 처리한다. 승인 창은 정확한 경로, SHA-256, 복구 위치를 보여주며 두 번째 파일 지문 확인 후 실제 이동한다.
- 결과·중복·UNKNOWN은 기존 OperationCoordinator를 사용. 실행 후 ACK가 유실되면 UNKNOWN을 보존하고 같은 Operation에 중복 이동을 수행하지 않는다.

## CDP 재연결 및 승인 반복

- 기존 \`CDPConnectionManager\`와 \`PersistentCDP\`는 이미 한 프로세스의 승인된 MCP stdio 연결을 재사용하고, 호출을 직렬화한다. 이번 PR에서 중복 연결 관리자나 자동 승인·승인 우회 코드를 **추가하지 않는다**.
- 같은 Core 프로세스 내 연결 살아 있음: 사용자가 별도 클릭을 반복하지 않음. 네트워크/전송 UNKNOWN: 새 연결로 자동 재전송하지 않음.
- Chrome 재시작·운영 Core 프로세스 재시작·사용자 동의 요청은 브라우저가 다시 승인하라고 요구하면 그 승인을 따르며 우회 금지. 승인 지속/재사용에 대한 추가 OS 구현은 후속 별도 보안 검토 항목.

## 수락 항목

1. 격리 파일 이동·동일 폴더 이름 변경·복원·중복 호출·UNKNOWN·파일 교체/해시 변경·경로 밖/보호 경로 차단을 시험.
2. 복구 삭제는 격리 UI YES/NO/무화면/시간 초과·확인 중 파일 변경·복구 위치 충돌을 시험. **실제 사람의 YES/NO 물리 클릭과 사용자 데스크톱 표시**는 감독관이 격리 Windows에서 확인해야 한다.
3. 프로세스는 실제 소유된 BCT 시작 영수증·정확한 지문으로 정상 GUI 종료만 허용하고, 운영/Chrome/RCC/Core·자식 프로세스·force 시도는 차단한다.
4. 고보안 Ed25519·키 경계·1회 토큰·기존 승인 회귀를 유지한다.
5. 기존 CDP 승인 연결 재사용·시리얼 실행 및 UNKNOWN 재전송 금지 회귀시험 확인.
6. GitHub 최신 HEAD CI SUCCESS, Worktree CLEAN, main과 정확한 차이, 감독관 물리 E2E 후에만 LIVE 수락.

### 고보안 선택형 유지
\`[approval_verifier] enabled=false\`는 그대로 유지한다. 일반 모드는 **별도 좁은 능력(capability)** 으로 동작하며 고보안 정책을 해제한 것이 아니다.

### 주의 및 한계
이 일반 모드는 같은 계정/세션에서 받은 BCT Work 요청을 신뢰하는 사용성 모드다. 같은 계정의 악성 프로세스에 대한 OS 수준 독립 서명 보안을 제공하지 않는다. 운영 보호/영구 삭제에 일반 모드를 사용할 수 없다. 사용자 승인 확인 화면이 실제 올바른 데스크톱에 표시되는지, 운영 Core 세션이 비대화형이라면 별도 사용자 데스크톱 어댑터가 필요한지는 감독관 격리 물리 E2E로 검증한다.
