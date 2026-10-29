# PR #347 — Windows 승인 계정 / Core 보안 경계 개발 및 감독관 인계 (2026-10-29)

## 정확한 정본과 범위
- 재사용 기반: PR #347 HEAD \`a8f2dffa36689a39a0504541b5ef75905beaf998\`, GitHub CI \`40787089393\` SUCCESS.
- Work: \`BCT-PR347-SECURITY-BOUNDARY-DEVELOP-20261029\`; 기존 \`feature/pc-safe-action-plans-20261029\` 격리 브랜치만 수정.
- 소스·운영 계정/ACL·main·LIVE·Chrome·RCC·프로세스·운영 파일·node-sync에 어떤 변경도 적용하지 않는다.
- 승인 UI, Ed25519 서명, 정확한 Work/Operation/request-hash, TTL, nonce 소비, 출처 있는 프로세스 시작 영수증, 가역적 이동은 기존 코드·시험 결과를 재사용한다.

## 보안 차단의 정확한 원인

이전 READ-only 실계측:
- \`D:\BCT\source\bct.toml\`, \`D:\BCT\runtime\state\state.sqlite\` 및 상위 \`runtime\releases\`에는 \`Authenticated Users: Modify\`가 확인됨.
- LIVE 릴리스 폴더는 보호 DACL이지만 조사 계정 소유 및 \`OWNER RIGHTS: FullControl\`이 확인됨.
- 기존 Core는 \`execute\`, \`write\`, \`process_session\` 등 범용 명령도 수행함. Core를 단순히 별도 사용자 SID로 전환하면서 이들 명령을 같은 프로세스 토큰으로 수행하면, Core 계정 스스로 DB·WAL/SHM 및 승인 영수증을 변경할 수 있다.
- 현재 \`approval_verifier.enabled=false\`, 실제 승인 개인키/공개키 등록은 미실시. 따라서 현재는 안전하게 비활성이나 **실사용 승인 경계 미확보**.

## 이번 최소 보완 (격리 구현)

새 \`bct.core.approval_boundary\`:
1. 서로 다른 SID 3개 필요: 일반 BCT 자동화(변경/개발 명령), 보호된 최소권한 Core 승인/실행 서비스, 별도 사람용 Approver 계정. 동일 SID·그룹(Administrators/System/Authenticated Users 등) 사용 금지.
2. Windows ACL은 보호 DACL 필수, owner는 SYSTEM/Administrators(issuer 개인키는 Approver 허용)만. 그룹이나 자동화 SID의 쓰기·삭제·ACL 변경·소유자 변경 권한이 하나라도 있으면 차단.
3. 정책 파일과 그 상위 폴더, 실제 로드된 Core 코드/패키지, 실행 Python 바이너리/상위 폴더는 Admin/SYSTEM 쓰기만 허용.
4. DB와 \`-wal\`, \`-shm\`, DB 상위 폴더는 Admin/SYSTEM/별도 Core SID 쓰기만 허용. Approver·일반 자동화 SID 쓰기 금지.
5. 승인키와 그 상위 폴더는 Admin/SYSTEM/Approver SID만 쓸 수 있음. 독립 승인 UI 실행본은 Admin/SYSTEM만 쓰며, Approver는 실행/읽기만.
6. **Core가 승인 효과를 처리할 때 일반 \`execute\`·\`write\`·\`process_session\`·\`deploy\` 등 범용 실행 capability를 같은 보호 SID로 노출하면 차단.** 보호된 P2 Gate는 별도 최소 정책/실행 맥락이 필요함.
7. 현재 Windows SID/고정 실행 파일 경로, 실제 로드된 승인 로직의 코드 경로, PowerShell 격리 모드(\`python -I\`), reparse/junction 경유를 확인하고 하나라도 불확실하면 승인 전에 차단.
8. 기존 \`ApprovalVerifier\`가 \`enabled=true\`일 때만 외부 서명검증 전에 Core 경계를 필수 확인. 기존 디폴트 \`enabled=false\` 유지.
9. 별도 승인 GUI 역시 Admin-owned 승인 manifest(\`%ProgramFiles%\BCTApprovalIssuer\boundary-v1.json\`)를 보호 ACL로 읽고 정확한 Approver SID·실행 모듈·승인키 위치와 DACL 확인 후 GUI 시작. 일반 BCT 작업폴더에서 GUI를 무작정 실행하면 차단.
10. 별도 실행/침해 시험 도구 \`scripts/p2_approval_boundary_audit.py\`는 READ-only; \`scripts/p2_dual_account_canary_probe.ps1\`는 정확한 \`D:\BCT\worktrees\p2-security-canary\` 하위의 감독관 설치 시험 fixture에서만 사용하고 그 외 경로는 거부. **이 턴에서는 canary를 실행하지 않음.**

### 3개 권한 경계 예시

|대상|일반 자동화 SID|보호 Core SID|별도 Approver SID|SYSTEM·Administrators|
|---|---|---|---|---|
|보호된 정책·공개키·로드할 코드/실행 이미지|READ 또는 거부, WRITE 거부|READ, WRITE 거부|READ 또는 거부, WRITE 거부|WRITE 허용|
|승인/Operation DB·WAL·SHM 및 상위 디렉터리|WRITE 거부|WRITE 허용|WRITE 거부|WRITE 허용|
|승인 UI 실행 파일/모듈|WRITE 거부|WRITE 거부|READ/EXECUTE 허용, WRITE 거부|WRITE 허용|
|암호화된 개인키·키 디렉터리|READ/WRITE 거부|READ/WRITE 거부|READ/WRITE 허용|관리자 비상 접근|

**주의:** 파일 ACL 검사만으로 역할 분리 완료가 되지 않는다. 현재 일반 BCT Core의 범용 실행 경로와 승인 서비스가 동일 보호 토큰을 사용하지 못하도록 실제 **별도 프로세스/서비스 보안 토큰** 및 인증된 인터프로세스 요청 경로가 필요하다. 위 표는 관리자 검토·격리 설치 대상이지 즉시 운영 ACL 변경 명령이 아니다.

## 독립 수락 시퀀스 — 감독관이 별도 계정에서 직접 실행할 항목

0. 운영이 아닌 별도 Windows 시험 컴퓨터/VM에서만 \`automation\` / \`core\` / \`approver\`의 서로 다른 비관리자 SID를 준비한다. 관리자가 프로그램·정책·DB·키 폴더를 별도 보호 ACL로 설정한다. 계정 생성·수정과 ACL 변경은 이 PR 개발 노드가 하지 않는다.
1. 독립된 관리자 세션에서 모든 파일과 **상위 디렉터리**에 대해 \`Get-Acl\`, 소유자 SID 및 ACL 보호 여부를 기록한다. 자동화 계정/일반 사용자 그룹의 WRITE/DELETE/WRITE_DAC/WRITE_OWNER 금지 확인.
2. 각각의 SID로 로그인하여 임시 canary 4개(정책, 상태 DB, 승인 실행본, 승인키)를 대상으로 \`scripts/p2_dual_account_canary_probe.ps1\`를 실행한다. 실제 SID를 확인하고 쓰기 열기 및 파일 교체 시도 결과를 기록한다.
3. Automation / 다른 일반 사용자 → 4개 canary 모두 WRITE·REPLACE = ACCESS_DENIED. Core → DB canary만 허용, 정책/코드/키 거부. Approver → key canary만 허용, 정책/DB/코드 거부. 관리자 → 정책/코드 변경은 보호된 관리 절차에서만 허용.
4. 일반 계정에서 writable source의 복제 승인 GUI 호출, \`--approve\`, 서명 함수 직접 호출, 개인키 읽기/대체, 공개키 교체 및 가짜 승인 토큰을 시도하되 **실제 운영 대상은 절대 사용하지 않는다**. 모두 거부·미적용이어야 한다.
5. 관리자가 보호된 \`python -I\` 기반 최소 Core Gate를 구성하고, 일반 \`execute\`·\`write\`를 보호 토큰에서 제거한다. 임의 실행이 가능하면 INVALID, 승인 활성화 금지.
6. 사용자가 독립 승인 계정에 직접 로그인한 상태로 승인 UI를 클릭하여, 경로/작업 대상/PID/부모·자식/Work/Operation/request hash를 읽고 YES·NO를 각각 시험한다. NO는 승인 토큰 없음. YES는 별도로 격리된 원본/대상 파일의 한 번만 이동 및 영수증 검증.
7. 만료, 대상/요청 해시 변조, 다른 Operation/Work, nonce 재사용, 정책 공개키 바꿔치기, 실행 UI 대체, DB/WAL/SHM 쓰기, 원본 효과 뒤 LOST ACK/UNKNOWN, Core/GUI 재시작을 시험하여 중복 효과 없음과 HOLD 정확성을 기록.
8. 적법한 서명 발급 경로가 실제 사용자 확인을 강제하는지 별도 리뷰한다. 현재 Python \`issue_after_human_confirmation(confirmed=True)\` 함수만으로는 Approver SID 내부 악성 코드의 자동 서명까지 차단할 수 없다. 해당 위협 모델이 필요하면 하드웨어 사용자 검증/Windows Hello 지원 키·인증된 브로커를 설계·시험 후 승인한다.
9. 결과 증빙은 권한/정확한 SID, ACL 원문(개인정보 제외), 승인/거부 결과, 효과 전후 SHA-256, Operation receipt/outcome, 물리 사용자 승인, 버전/서명 해시. **비밀번호·개인키·승인토큰 전문은 기록하지 않음.**

## 시험 결과에 대한 범위
- 순수 DACL/SID·코드 로드/계정 격리 가정·정책 범용 명령 거부 테스트는 격리 Python/PowerShell READ-only에서 실행할 수 있음.
- 실제 운영 경로 ACL 수정·계정 생성·운영 프로세스 종료·파일 이동은 실행하지 않음.
- 두 개의 실제 별도 Windows 사용자 토큰 및 물리 YES/NO E2E는 개발 워크트리에서 입증 불가, 감독관의 격리된 시험 환경에서 수행해야 한다.

**보안 완료 전 최종 판정: PARTIAL (SECURITY_READY는 HOLD).** PR #347 Draft와 \`approval_verifier.enabled=false\` 유지. main 병합/LIVE 배포 금지.
