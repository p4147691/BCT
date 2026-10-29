# BCT 기본 PC 제어 기능 전수 조사 및 개선 인계 — 2026-10-29

## 범위·운영 원칙

- 조사 기준: GitHub origin/main \`4819c29f5ad3390b62fda752653680990b75c418\`, PR #344 MERGED (2026-10-29 00:18 KST).
- 조사 단계: READ-ONLY. 코드·서비스·Windows 창·Chrome/RCC/Monitor 변경 없음.
- 개발 단계: 격리 Worktree \`D:\BCT\worktrees\pc-baseline-readonly-toolkit-20261029\` 및 별도 PR만 수정. main 병합·LIVE 배포 금지.
- 기존 Work·Operation·Policy와 실패 미확정(UNKNOWN) 처리 및 Claim/Lease를 재사용한다.
- 상태의 의미: 구현됨=기존 경로가 존재, 개선=기존 권한 내 부족한 사용성 보완, 신규 필요=독립 안전 승인·E2E가 필요한 미구현 범위. 기존 기능의 실사용 E2E까지 전부 PASS했다는 뜻은 아니다.

## 기능별 전수 분류

|분야|기존 구현|판정/우선순위|현재 작업|
|---|---|---|---|
|정확한 파일 읽기·폴더 목록|read(file/directory_tree/batch/snapshot), Work 경로 제한|구현됨 P1|변경 없이 재사용|
|이름으로 파일·폴더 검색|read directory_tree만, 파일 이름 질의 API 없음|개선 P1|**read.search** 신규 확장 구현·테스트|
|두 파일 내용 비교|텍스트 read SHA는 있지만 바이너리 정확 비교 수동|개선 P1|**read.compare**, SHA-256·크기, 불확실하면 미확정|
|중복 파일 검증/정리 계획|경로·파일 목록 읽기만, 중복 해시 그룹화 없음|개선 P1|**read.duplicates**, 크기 후보→실제 SHA-256. 삭제·이동 안 함|
|Windows 폴더 열기|desktop_explorer_folder_open (PR #344 이미 병합)|구현됨 P1|중복 구현 금지, 개발하지 않음|
|프로그램 실행/세션 조회|desktop_program_launch, execute, process_session|구현됨 P1|기존 계약 유지|
|실행 프로그램 검색·정확한 창 제어|desktop_explore, desktop_application_target, window_activate/manage|구현됨 P1|정확한 HWND 및 Lease 보호 재사용|
|화면 캡처·분석|desktop_capture 이미지 반환, AI 해석은 호출 계층|구현됨 P1|기존 캡처 재사용; 자동 화면 인식/OS 조작 임의 확대 없음|
|오류 진단|system_inspect(process/port), read, desktop_session_status, operation_get|개선 P1|**system_inspect.diagnose** 프로세스 질의+포트 다중 조회를 한 영수증으로 결합|
|검증·영수증/완료 선언|verify, test, github_pr_status, operation_get, claim_reconcile|구현됨/개선 P1|기존 기능 활용; LIVE 실사용 E2E 자동 PASS는 별도 수락|
|파일 이동·삭제·대량 정리|write는 SHA 조건부 원자적 텍스트 쓰기, 삭제/바이너리 이동 범위 아님|신규 필요 P2|보류: 명시적 대상·승인·복구/undo·정확한 드라이런 계약 설계 필요|
|임의 프로세스 강제 종료|process_session.stop은 소유 작업의 세션에 제한|신규 필요 P2|보류: 다른 노드/서비스 보호·PID birth·승인·영수증 검증 선행|
|경로 없는 자연어 위치 추정|desktop_explore.paths 및 사용자 문맥, 검색 대상 Work roots|개선 P1|검색 API 제공; ChatGPT 호출측의 경로 유추 및 안전한 Work 범위 지정은 별도 검증|
|장애 자동 복구·다른 데스크톱 이동|정확한 Window Lease, virtual-desktop fence, UNKNOWN 보호|구현됨/개선 P2|임의 전환·반복 전송/복구 금지; 기존 보호 유지|

## 개발한 변경과 호출 계약

### read — search (읽기 전용)

\`{"operation":"search","path":"D:\\some\\authorized\\folder","query":"*.safetensors","depth":3,"max_entries":500,"limit":100,"timeout_seconds":10}\`

- 기존 Work roots에서만 검색, 기본 substring 검색과 glob 지원, 폴더/파일 모두 검색
- reparse point/symlink는 따라가지 않고, 부분 결과는 \`complete=false\`, \`truncated=true\`
- 폴더 변경·파일 복사·이동·삭제 없음

### read — duplicates

\`{"operation":"duplicates","path":"D:\\some\\authorized\\folder","depth":3,"max_entries":500,"max_hash_bytes":268435456,"timeout_seconds":10}\`

- 같은 파일 크기인 후보만 실제 SHA-256으로 검증. 완전 해시가 없는 대용량 후보는 중복 확정 금지.
- \`delete_authorized=false\`, \`unverified_files\`, \`complete\`로 판정 범위 명시

### read — compare

\`{"operation":"compare","path_a":"D:\\authorized\\one.bin","path_b":"D:\\authorized\\two.bin","max_hash_bytes":268435456}\`

- 두 파일이 모두 Work roots 아래에 있는 일반 파일이어야 함. 크기·SHA-256 근거로 일치 여부 확인.
- 해시 예산·시간 초과, 실행 중 파일 교체는 \`equal=null,complete=false\`로 반환. 원본 변경 없음.

### system_inspect — diagnose

\`{"operation":"diagnose","query":"python","ports":[18790,18791],"limit":50}\`

- 기존 process_list/port 조회 결합; 텍스트 질의 또는 포트 중 하나 이상 필수
- 포트 최대 8개, 프로세스 제한 최대 200개, 쓰기/종료 없음

## 보안·호환성

- 새 권한이나 별도 서비스가 아닌 기존 read/system_inspect 계약에 선택적 operation 추가
- Work root 경계 검사, reparse 차단, 파일 해시 전후 신원 확인, bounded entries/time/hash budgets
- 모든 정리 출력은 검토용: **삭제 권한으로 확대하지 않는다**
- 기존 정확한 경로 읽기, directory_tree, 기존 process/port 조회 계약 유지
- Chrome·RCC·Monitor·Core 실행본 변경 금지

## 감독관 인계·LIVE 검증 조건

1. 현재 HEAD·대상 PR·main SHA 차이와 실제 소유권 확인
2. 신규 집중 회귀, 기존 파일·실행·배포 import closure·모듈 구조·MCP 도움말 검증, GitHub required checks 모두 PASS 확인
3. main 병합은 감독관 단독 수행
4. 정확한 LIVE 배포 후 실제 Work roots 아래 검색/중복/바이너리 비교와 진단을 승인된 경로로 검증하고 반환 영수증 확인
5. 부분 검색/해시 예산 초과가 "완료"로 오인되지 않는지 실제 파일로 검증
6. Live SHA/Generation 및 Work/Operation 결과를 감독관이 보고

## 보류 항목

- 승인 게이트가 필요한 실제 파일 이동/삭제·임의 프로그램 종료는 이번 읽기 전용 개발의 범위에 넣지 않았다. 기존 사용자 권한을 확대하면 안 되므로 별도 보안·원복 검수 후 개발해야 한다.
- 화면 AI 분석, 자연어 대상 추론, 자동 작업 조합은 PC 제어 명령의 호출측 책임이며 새로운 OS 권한 없이 기존 도구를 호출하는 방식으로 검증한다.
