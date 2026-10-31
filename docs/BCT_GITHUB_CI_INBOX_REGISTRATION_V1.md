# GitHub CI → BCT Inbox 수신 운영 계약 (2026-10-31)

## 확인된 경로
- BCT에는 github_run_watch가 존재한다. 정확한 repository/run_id/head_sha, Work 및 initiator_node_id를 입력으로 받아 기존 github_run_inbox / github_run_inbox_recipients에 저장한다.
- 완료 시 GitHub Actions API에서 run identity·결론·실패 job을 검증하고 수신자별 unread를 기록한다. 기존 bct_github_inbox_get(별칭 bct_inbox_get)은 Work 소유 범위에 맞춰 읽는다.
- 등록한 감시는 BackgroundOperation으로 분리되어 사용자 대화나 다른 Work의 종료를 기다리게 하지 않는다.
- Manager Wake는 notify_manager opt-in, 신뢰된 manager epoch, idle, 기존 relay가 모두 충족될 때만 전송하며, UNKNOWN은 무재전송이다.
- 현재 github_pr_create/github_push에는 신뢰된 initiator node + exact Actions run ID를 자동 연결하는 경로가 없다. 단지 CI가 시작됐다고 추측한 recipient/Run ID로 가입하면 안 된다.

## 현재 반영된 보완
- bct.toml [github_inbox] timeout_seconds를 300→3600으로 늘려 Core CI가 5분을 넘는 경우의 조기 TIMED_OUT을 방지한다.
- 설정 누락 시의 기본 감시 제한도 3600초다. 외부 GitHub API가 불통이거나 완료가 확인되지 않으면 TIMED_OUT이며 CI 실패를 의미하지 않는다.
- GitHub 인증과 CI 실행 SHA 불일치 시 FAILED(identity mismatch)로 기록하고 무Claim·기존 UNKNOWN·영속 업무 상태는 보존한다.
- 실사용 완료된 GitHub main CI #41168893110 / 3a0b786d5b29738d4aa599ee8ce41bf831e6283f를 임시 격리 BCT DB에서 github_run_watch로 수신: SUCCESS / unread=true / SHA 일치 / unresolved_claims=0.

## CI 시작 시 자동 등록을 위한 남은 연결 조건
1. GitHub 이벤트의 exact repository, run_id, head_sha 검증. Run ID가 관측되지 않았다면 새 전송이나 임의 ID 등록을 하지 않는다.
2. initiating Work가 github_run_watch 권한을 갖고 있으며 실제 initiator_node_id/Manager node id가 신뢰된 원본 바인딩으로 확인돼야 한다. 문자열로 임의 관리자 지정 금지.
3. Work에 동일 run_id/SHA가 등록돼 있으면 동일 Inbox 영수증·수신자를 재사용. 완료 전에는 읽기 전용 확인 외 재시작/중복 감시 불필요.
4. GitHub push/PR 생성 또는 기존 오케스트레이션의 CI run 관측 직후, idempotent 등록을 자동 실행하는 결합점을 마련한다. 신규 중복 저장소·별도 CI 폴러는 만들지 않는다.
5. 기존 manager wake 신뢰 경계/idle/epoch, RCC 효과 UNKNOWN 보존. CI 알림 성공을 자동 병합·배포 승인으로 해석하지 않는다.
6. CI 필수 성공 검증은 Inbox 완료 영수증의 exact SHA와 실제 필수 검사 명단 대조. Inbox가 비어 있으면 관측 미등록/권한/전송/시간초과를 분류하고 필요할 때만 단일 조회.
7. 검증된 신뢰된 node binding이 없는 환경에서는 AUTO_REGISTRATION_BLOCKED, 비차단. 반복 CI polling을 사용자 기본 경로로 되돌리지 않는다.

이 문서는 자동 가입 완료를 의미하지 않는다. 운영 Core/RCC/Monitor, PR #381, node-sync, UNKNOWN·Claim은 변경 대상이 아니다.
