# BCT 인수인계

## 진행 규칙 — Windows UTF-8/언어 설정 불변성

사용자 요구: Windows 국가/언어 설정 또는 ``Beta: 세계 언어 지원을 위해 UTF-8 사용``
토글이 바뀌고 재부팅된 뒤에도, BCT의 설정 읽기·CAS 쓰기·해시·RCC/ChatGPT 전달은
오류나 의미 변화 없이 계속되어야 한다. 이는 단순 콘솔 표시 품질이 아니라 릴레이
설정과 메시지 원문의 호환성 계약이다.

설정/프로토콜/해시는 현재 ACP·OEM 코드 페이지에 의존하지 말고 명시적 UTF-8 바이트를
사용한다. UTF-8 BOM 및 기존 UTF-16은 안전한 읽기 호환 대상으로만 취급하고, 새 CAS
저장은 UTF-8 정본으로 기록한다. 판별 불가·손상 입력을 현재 코드 페이지로 억측해
복구하거나 자동 덮어쓰지 않는다. 한국어·이모지·결합 문자·개행을 포함한 round-trip 및
해시 동등성 회귀를 유지한다. 실제 시스템 로캘 변경이나 재부팅은 사용자 명시 승인 없이는
수행하지 않는다.

## 진행 — RCC 신규 대화 지연 결과의 무재전송 회수

기존 `rcc-new-chat-live-e2e-9c1675e-20261021-02`는 탭·원문·응답이 실제로 각각 한 번만
존재하지만, 응답이 호출 제한 시간 뒤에 끝나 영속 상태가 `SUBMIT_UNKNOWN`에 머물렀다. 첫
readback 보완은 저장소를 읽기만 했기 때문에 이를 pending으로 반환했고 exact Claim을 정산하지
못했다. 같은 operation을 다시 보내면 안 된다.

후속 최소 수정은 `SUBMIT_INTENT`/`SUBMITTED`/`SUBMIT_UNKNOWN`이며 exact tab/window/text hash가
있는 기존 영수증만 현재 DOM에서 한 번 재관측한다. 탭 생성과 메시지 제출 함수는 호출하지 않고,
완료 응답이 확인된 경우에만 원본 operation ID 아래 `RESULT_PERSISTED`를 기록한다. focused 회귀는
추가 생성 0회·추가 제출 0회·상태 조회 1회와 terminal 영수증을 확인했고 전체 RCC JS 및 Python
통합 회귀가 통과했다. exact-head CI, candidate 배포, same-ID reload, 원본 operation 무재전송
reconcile가 남았다.

## 진행 — RCC 신규 대화 영수증 회수와 유지보수 Claim 분리

신규 대화 operation `rcc-new-chat-live-e2e-9c1675e-20261021-02`는 실제로 탭 하나와 원문 한
건, ChatGPT 응답 한 건을 만들었으므로 재전송하지 않는다. 새 영수증 저장소 조회와 원본
operation ID readback 결함은 각각 `362b20c`, `a3240a5`에서 수정됐다. 남은 병목은 그
FINISHED/UNKNOWN의 전역 RCC Claim이 exact RCC payload의 공식 same-ID reload까지 차단한 것이다.

reload는 이제 `rcc-instance:<id>:maintenance:reload-extension` Claim을 사용한다. Store 트랜잭션은
RUNNING RCC-wide 효과와 maintenance를 양방향 차단하지만, 실행자 없는 FINISHED effect Claim은
기록 그대로 둔 채 reload와 공존시킨다. reload 직전 exact instance/session과 모든 관측 endpoint의
`generating=false`를 읽기 전용으로 확인한다. focused RCC/Core/Claim 83개 회귀와 compileall,
diff check가 통과했다. exact local main commit·GitHub CI·Core 배포 후 RCC를 한 번만 reload하고,
원본 operation의 저장된 result를 read/reconcile해 no-resend와 Claim 정산을 확인하는 단계가 남았다.

## 진행 — BWM 섬네일 노드 번호 충돌 회피

같은 데스크톱에서 서로 겹친 두 Chrome 창의 노드 번호가 모두 각 투영 창의 좌상단을 사용해
뒤 번호를 가리던 표시 결함을 수정한다. `monitor-bct-thumbnail-projection.js`의 단일 의미 계층은
유지하고, 실제 투영 사각형과 배지 크기를 기준으로 좌상단·우상단·좌하단·우하단 중 먼저 비어
있는 위치를 결정적으로 선택한다. 창/대화 identity, exact HWND 계약, 캡처 이미지와 갱신 주기는
변경하지 않는다. 같은 topology를 다시 그려도 위치가 누적 이동하지 않아야 한다.

격리 후보는 focused projection/구조/배포 회귀를 통과한 뒤 로컬 main 계약으로 병합하고 exact
Monitor 설치본 배포와 same-ID reload 후 실제 겹친 창 표시를 확인한다. 상세는
`docs/exec-plans/active/BCT_MONITOR_THUMBNAIL_BADGE_COLLISION_20261021.md`를 따른다.

## 완료 — 로컬 main 정본 전환

운영 결정은 `D:\BCT\source`의 로컬 Git `main`을 공식 소스 정본으로 사용하고 GitHub는
게시·백업·리뷰·CI 감사 원격으로 두는 것이다. 기존
`BCT-LOCAL-GIT-AUTHORITY-INTEGRATION-ISOLATED-20261020-01`과
`feat/local-authority-integrated-20261020`을 재사용해 후보를 GitHub main `09a5db7...` 위로
충돌 없이 리베이스했다. `[git_authority] mode="local"`, exact local merge 계약,
remote merge/sync 차단, `IN_SYNC`/`SYNC_PENDING`/`SYNC_CONFLICT` 게시 상태를 포함한다.

전환은 완료되어 `AGENTS.md`의 source authority 계약과 실제 local/origin main 운영에 사용 중이다.
이전에 전역 `PYTHONPATH`가 `D:\BCT\source`를 가리켜 다른 코드를 검사한 시행착오가 있었으므로,
worktree 검증은 반드시 해당 worktree의 `src`를 명시한다. 이후 전달 흐름은 exact local main
commit을 기준으로 GitHub fast-forward 게시·CI 감사와 runtime release를 서로 구분한다.

## 진행 — BWM 복구 버튼 공식 경로 연결

BWM 상단의 `RCC 리로드`, `BCT 시작·복구`, `MCP 터널 복구`, `BC 도구 새로고침`을 source-only로
연결했다. RCC는 현재 exact instance 하나와 BCT durable receipt를 요구한다. Core/Tunnel은 Monitor
Native Host가 각각 고정된 `BCT Core Supervisor`, `BCT Tunnel Supervisor` 예약 작업만 호출하고
health/ready를 다시 확인한다. BC는 선택된 정확한 ChatGPT conversation/tab/window를 재대조하고
생성 중이 아닐 때 그 탭만 reload한다. 임의 command/path, shell, Chrome UI 자동화는 추가하지 않았다.

exact adapter와 Monitor 계약 검사, 관련 Python 20 tests, Native Host compile은 PASS다. source commit
`2397853cda06b79ffb514344a267bbdbfc6a4893`, PR #260, BCT CI run `39517865233`의 scope/preflight,
Core 4 shards, Browser Bridge는 전부 SUCCESS다. 설치본·Chrome·Native Host·Core·RCC·터널은 변경하거나
재시작하지 않았다. main 반영과 LIVE 배포·버튼 클릭 수락시험이 남았다. 상세는
`docs/exec-plans/active/BCT_MONITOR_RECOVERY_ACTIONS_20261021.md`에 있다.

별도 BWM 복구 버튼 LIVE E2E는 로컬 main 정본 전환 직후 같은 검증 SHA에서 연속 수행한다.

## 진행 — BWM UI·썸네일 HWND 수렴 보수

Monitor 상단을 `BWM`과 실행 버전 중심으로 단순화하고, BCT health 정상일 때 버전만 초록색으로
표시하도록 source를 수정했다. `BCT 정상 · G...`와 BCT 상태 버튼은 향후 정보창 범위로 제거했다.
복구 메뉴 항목은 상단 버튼으로 옮겼고, 현재 공식 효과 경로가 검증된 확장 리로드만 활성이다.
2열/3열 선택기는 제거하고 3열 기본, 노드 번호 글자 확대를 적용했다.

썸네일 번호 누락의 실제 원인은 노드 조회가 desktop topology보다 먼저 끝난 뒤 exact HWND 대조가
재실행되지 않는 순서 결함과, RCC transient `UNAVAILABLE`에서 이전 exact binding까지 버리는
계약 결함이었다. topology 준비 후 최대 세 번의 bounded 대조를 추가하고, cached last-known OPEN은
Native가 같은 Chrome HWND를 5초 이내에 신선하게 관측할 때만 기존 binding을 retain한다. cached
행은 새 binding을 만들 수 없다. 실제 shell+contract 회귀에서 동일 창 N4/7/9 유지와 stale 제거를
검증했다. source commit/main `802c5a3fb90f6c4e04cc111b6e61a481027b0236`과 GitHub Actions
`39477884804`는 SUCCESS다. exact runtime 5파일을 설치본에 반영하고 공식 publish gate로
`2.0.11`/token `d589c3f24c594be1b461a5febf597070`을 발행했다. 변경 전 파일은
`D:\ChromeExtensions\DesktopWindow-Monitor\backup\monitor-live-802c5a3-20261021-035300`에
보관했다. publish 직후 renderer는 `2.0.10`과 이전 token을 보고해 same-ID reload가 필요했고,
보안 정책상 확장 URL 자동 조작은 우회하지 않았다.

사용자의 공식 버튼 재로드 뒤 `2.0.11`과 publish token ACK 일치를 확인했다. 그러나 재로드 직후
읽기 전용 LIVE 대조는 RCC가 다시 OPEN이고 N4/N7/N9가 같은 `window_id 594834491`에 있어도
`mapped_windows: 0`이었다. 재로드 시 선택 탭이 비-ChatGPT이면 memory-only exact binding을
재생성할 대화 키가 없기 때문이다. 후속 source는 표시와 조작 권한을 분리했다. 번호/노란 표시만
Chrome window_id의 현재 bounds와 fresh Native Chrome HWND bounds가 허용 오차 안에서 유일하게
일치할 때 display-only binding을 사용한다. 동일 bounds 후보가 둘이면 거부한다. 더블클릭 이동 등
실제 부작용은 기존 conversation exact binding만 허용한다. 이 후속 보수는 source 회귀 PASS,
commit/CI/설치본 publish/reload/LIVE 수락 전이다.

우클릭 이름 변경은 UI 결함이 아니라 기존 대화별 UNKNOWN rename claim에 의해 안전 차단된 대상이
남아 있다. 이를 재전송하거나 claim 해제하지 않았고, 화면 오류만 사용자가 이해할 수 있는 문구로
바꿨다. generating 아이콘은 editable composer가 아니라 RCC telemetry 기준을 유지한다.

## 진행 — Monitor 노드 클릭 강조·더블클릭 브라우저 이동

source base `0645a13839467387aa7b810d1b81593aef9efd5d`에서 Monitor의 BCT/RCC 노드 카드와
현재 session exact `window_id → HWND` 계약을 연결했다. 한 번 클릭은 연결된 물리 Chrome 창의
썸네일/preview에 노란 테두리를 표시하고, 더블클릭은 Native Host의 데스크톱별 HWND 재대조 후
해당 데스크톱으로 전환하고 그 Chrome HWND를 foreground로 활성화한다. exact HWND가 없으면
어떤 창도 추측하거나 전환하지 않는다.

동작은 `monitor-bct-node-interaction.js`로 분리했으며 focused 계약, Monitor 구조/문법,
번호·최소화·SVG·backpressure·현재 session HWND 회귀가 PASS했다. 현재 LIVE 읽기 전용 대조는
ChatGPT 탭 3개, 물리 ChatGPT Chrome 창 1개, binding 1개, rejected 0개다. GitHub main 반영,
원격 CI, 설치본 publish/reload, 클릭/더블클릭 LIVE 수락시험은 아직 남았다.

별도 인수된 PR #247/#251은 정확한 HEAD·기존 CI SUCCESS·현재 MERGEABLE/CLEAN만 재확인했다.
별도 승인이 없으므로 병합·배포하지 않았고, 과거 UNKNOWN 결과도 성공으로 바꾸지 않는다.

## 진행 — Monitor 번호·RCC 이름 변경 통합 복구

2026-10-20 화면 재현에서 Monitor가 새 설치본을 실행 중이라고 오판했고 실제 renderer는
`v2.0.6`이었다. 동시에 짧은 RCC 조회 timeout이 정상 3개 노드를 `0개`로 덮어썼으며, RCC V2
정리 때 `rename-conversation` 실행기만 제거된 상태에서 Monitor UI가 계속 노출돼 이름 변경이
항상 실패했다.

source는 실제 reload + exact runtime telemetry를 배포 성공 조건으로 바꾸고, bounded 조회
실패 시 마지막 검증 tab identity를 stale 표시용으로 보존하며, RCC rename을 exact
session/tab/conversation과 전용 영수증을 가진 독립 domain/content 모듈로 복구했다. 다른 legacy
mutation은 계속 차단된다. RCC RC3 48파일 aggregate는
`9ae94c72398d96ee01a6812478fce23972b76ea2bc42f783099e67b1fb73fd62`다. RCC Node 24개 및 관련
Python 77개와 Monitor 번호/reload 회귀는 PASS했다. 다음 순서는 commit/push → exact-head CI →
BCT Core/RCC/Monitor exact payload 배포 → 실제 loaded version 확인 → 열린/최소화 번호와 새
unclaimed 대화 이름 변경 LIVE E2E다. 기존 UNKNOWN rename claim은 재실행하거나 강제 해제하지
않는다.

## 완료 — RCC Rebuild V2-6 정리·종료

RCC Rebuild V2-1~6을 완료했다. LIVE `D:\ChromeExtensions\RCC\extension`은 RC2 exact
46파일, aggregate
`e7b0bd98b74fd982031565c3701fe68f0c7b45e2984deba8c490867272756c39`다. active loader graph는
35파일이며, 나머지 11개는 향후 명시적 browser management capability를 위해 보존한 optional
Adapter/contract다. 제외 legacy 5개는 LIVE에 없어서 LIVE 삭제는 0개다.

RC1 rehearsal/failed candidate, 중복 pre-RC2 rollback, 과거 extension backup 10개와 빈 PR
staged 디렉터리 등 15개 디렉터리·452파일·5,587,932 bytes를 검증 후 정리했다. 현재 LIVE,
Native Host, binding, Chrome은 변경하거나 reload하지 않았다. 최신 복구본
`D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-rc2-20261020-184845`과 exact RC2 rehearsal
`D:\BCT\runtime\rehearsals\rcc-rebuild-v2-rc2-e7b0bd98`은 유지했다. V1/V2 실행 문서는
`docs/exec-plans/completed/`로 닫았다. 최종 구조·manifest·rollback·acceptance 영수증은
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_STAGE6_CLOSEOUT_20261020.md`에 있다.
종료 기록 commit `aef81006a3c611da75b8af96397ecc6702010ba6`의 BCT CI run
`39404680776`도 PASS했다.

남은 Browser Adapter는 불필요 구파일이 아니라 의도적으로 비활성 보존한 기능이다. 별도 설계
전에는 active loader와 Simple Relay 권한에 연결하지 않는다.

## 완료 — RCC Rebuild V2-5 RC2 LIVE 전환

사용자 허용 뒤 RC1 46파일을 exact backup 후 단일 LIVE 전환하고 same-ID reload 1회를 수행했다.
state/probe는 기존 Manager `6ad5afa4-b1e0-83ee-8692-aec4bb51523e`와 Worker
`6ad4bb5d-6624-83ee-b045-e57fdad5120e`를 정상 확인했다. 첫 Manager→Worker 수락시험은
`NOT_APPLIED / RELAY_EXACT_USER_TURN_NOT_CONFIRMED`를 반환했지만 Worker에 새 생성 lifecycle이
관측되어 계약 불일치로 판정했다. 같은 원문을 재전송하거나 반환하지 않고 39파일 rollback
baseline으로 원자 복구하고 reload했다. 설치본 핵심 SHA, Native Host, binding은 전환 전 값이다.

원인은 DOM 가상화 환경에서 user node 개수 증가를 요구한 제출 fence와, content의 `UNKNOWN`을
background가 `submitted:false`만으로 `NOT_APPLIED`로 축소한 분류다. RC2는 새 turn identity로
제출을 확인하고 클릭 직후 복구 record를 먼저 저장하며 명시적 `NOT_APPLIED`만 재시도 가능으로
분류한다. exact source commit `447c6bb5296e8a8bb7f9896d65ed49e48a385afb`의 CI run
`39402641746`은 preflight, Core 4 shard와 Browser Bridge 전체 PASS다.

RC2 46파일 aggregate
`e7b0bd98b74fd982031565c3701fe68f0c7b45e2984deba8c490867272756c39`를 LIVE에 단일 전환하고
same-ID reload 1회를 수행했다. 새 수락 operation
`rcc-v2-5-rc2-m2w-20261020-01`과 `rcc-v2-5-rc2-w2m-20261020-01`은 각각 한 번
`SUBMITTED`였다. 반환 응답은 10자, SHA-256
`5365e0b45f4a830703aa1a16bc1c9dedd3ec5ea7403d50f878612d3e44bd56f5`이며 Manager와 Worker
양쪽 generation 완료 후 Core shadow `matches:true`를 확인했다. RC2 전환 backup은
`D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-rc2-20261020-184845`이고 Native Host·binding은
변경하지 않았다. 후속 V2-6에서 zero-caller 구파일과 보존 backup을 검토해 안전한 범위만
정리했고 실행 문서를 completed로 닫았다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_STAGE5_LIVE_CUTOVER_20261020.md`에 있다.

## 완료 — RCC Rebuild V2-4 비-LIVE Release Candidate

V2-1~3 source payload를 `RCC_REBUILD_V2_RC1` 46개 exact 파일로 조립했다. active loader graph,
domain/platform dependency, allowed message matrix, storage/wire, extension ID/Native Host 계약을
`modules/rcc/release/verify_release_candidate.py`와
`modules/rcc/release/rcc_v2_rc.json`으로 자동 검증한다. candidate aggregate는
`ce3a33bb107dc74eb23da50d0d48a85dab656c69ee65e90caca763cde55f1606`이다.

Chrome Extensions 공식 API 점검에서 Content Script sender 검증 누락, 활성 호출자 없는
`webRequest` permission, 차단된 legacy runtime 메시지를 보내는 popup을 발견했다. source에서
runtime/content sender를 fail-closed로 검증하고 popup을 `relay:getState` 전용 read-only 화면으로
바꿨다. Simple Relay 원문/UUID/storage key/wire 이름은 유지했다.

현재 LIVE 39개 파일은 rollback aggregate
`93b1cfdc4e6602ddfb7de46b6fa00eb10173db01f911c1530c952cc1439e583b`와 exact 일치한다. 후보는
`D:\BCT\runtime\rehearsals\rcc-rebuild-v2-rc1-ce3a33bb`에만 조립했고 extra/missing 0개다.
RCC Node 23개, focused Python 17개, 전체 BCT Python 845개, candidate/LIVE verifier,
compileall, diff check가 통과했다. exact implementation SHA
`62049dc4810e03c86f9b1b92b3c184d303df488e`의 GitHub Actions run `39398670419`도 preflight,
Core 4개 shard와 Browser Bridge 전체 PASS다. LIVE RCC 설치본, Chrome, Native Host와 binding은
변경하지 않았다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_STAGE4_RELEASE_CANDIDATE_20261020.md`에 있다.

## 계획 — RCC Rebuild V1

RCC를 기존 5,000줄 실행부에 기능을 계속 더하는 방식으로 유지하지 않는다. 새 구조는
conversation UUID 기반 Core, Manager/Worker relay binding, verbatim Relay, 선택 모듈, legacy
read-only 경계를 갖는다. extension ID/path, Native Host registration/path, Chrome storage와
기존 conversation UUID는 전환 중 불변이다. 실제 단계와 exact path/identity/reload/rollback
gate는 `docs/exec-plans/completed/BCT_RCC_REBUILD_V1.md`에 고정했다. Simple Relay V0는 이 계획의
임시 Relay 기반이며 legacy execution 제거 전에는 새 기능을 legacy 경로에 추가하지 않는다.

전환은 전면 교체가 아니라 0) 기준선/복구 묶음, 1) source-only Core 추출, 2) read-only shadow,
3) 기존 열린 탭과 content protocol 호환, 4) Manager→Worker 단일 전송, 5) Worker→Manager 반환,
6) legacy 변경 경로 차단, 7) 호출자 0 확인 후 제거 순서다. 후보 파일을 먼저 배치하고 loader를
마지막에 바꾸며, 각 gate마다 same-ID reload와 두 conversation UUID의 exact resolve를 확인한다.
읽기 실패는 복원할 수 있지만 변경 요청 실패를 legacy로 자동 재시도하지 않는다. 이미 보냈을
가능성이 있는 `UNKNOWN` 효과의 중복 전달을 막기 위한 보호 규칙이다. 다음 실행 단위는 LIVE
코드 변경이 아닌 0단계 기준선 동결과 비-LIVE 임시 디렉터리에서의 exact backup 복구
rehearsal뿐이다.

## 완료 — RCC Rebuild V1 0단계 기준선·비-LIVE 복구 rehearsal

2026-10-20 09:44 KST에 RCC의 LIVE extension ID/path, Native Host registry/manifest/executable,
Simple Relay V0 binding과 대상 대화 상태를 읽기 전용으로 고정했다. Manager/Worker conversation
UUID는 각각 열린 endpoint로 해석됐고 두 대화 모두 OPEN·비생성중이었다. LIVE extension 32개
파일을 D:\BCT\runtime\backups\rcc-rebuild-v1-baseline-20261020-093700에 백업하고,
D:\BCT\runtime\rehearsals\rcc-rebuild-v1-baseline-20261020-093700에만 다시 복원했다.
원본↔backup, backup↔rehearsal은 각각 SHA-256 불일치 0건이다. Native manifest/executable도
backup과 일치한다. 확장 reload, Native Host 재시작, Chrome 탭 동작, 대화 전송, storage 변경은
없었다.

source와 LIVE의 실행·표시 payload 29개 파일은 모두 일치한다. source-only test/fixture 9개와
LIVE-only 비실행 이전 테스트/backup 파일 3개는 실행 payload 불일치가 아니라 명시적으로
분리한 잔존 파일이다. 상세 기준선과 복구 증거는
docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE0_BASELINE_20261020.md에 있다. 다음 단계는
LIVE에 손대지 않는 source-only Core 분리다.

## 완료 — RCC Rebuild V1 1단계 source-only Core 분리

source에만 modules/rcc/extension/core/identity.js, state.js, conversation.js, transport.js를
추가했다. 각각 UUID 기반 exact tab 해석, endpoint 상태 판정, 제출·응답 계약, transport 결과와
자동 재시도 금지 경계를 순수 함수로 분리한다. manifest, background loader, background/content
scripts, Native Host, Chrome storage, Relay binding은 변경하지 않았고 새 Core는 현재 실행 경로에
import되지 않는다. Core/기존 Simple Relay/Relay Core/identity/result 관련 focused Node tests
9개와 syntax/diff 검사가 통과했다. LIVE 설치 경로에는 core 디렉터리가 없고 기존 active
content.js source/LIVE SHA-256도 일치한다. 상세는
docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE1_SOURCE_CORE_20261020.md에 있다.

다음 2단계는 installed payload 후보 배치와 same-ID extension reload가 필요한 read-only Shadow다.
현재 source-only 제약 아래에서는 시작하지 않는다.

### 검증 기준선 보정

1단계 CI에서 `tests/test_rcc_source_baseline.py`가 과거 `1.0.21 / 2026-10-15` payload
해시를 기대하는 것을 확인했다. 0단계에서 source와 LIVE가 이미 같은 `1.0.23 /
2026-10-20-simple-relay-return-v0`임을 동결했으므로, 설치 payload나 실행 경로를 바꾸지
않고 테스트의 release baseline만 그 확인값으로 갱신했다. 이 보정은 source-only이며
extension reload, Native Host, Chrome 탭, Relay binding에 영향을 주지 않는다.
수정 뒤 `tests.test_rcc_source_baseline` 17개와 새 `test_rcc_core_v1.js`가 통과했다.
후속 CI에서 발견한 Handoff layout test의 역사 기록 오판도 source test에서만 보정했다.
현재 상태는 여전히 문서의 SHA가 아니라 `origin/main`·`runtime\\current.json`·health
`release_sha`의 기계적 일치로 판정한다.
GitHub Actions `BCT CI` run `39351244745`는 보정 뒤 전체 통과했다. 사용자가 이후 2단계의
installed payload 변경 및 same-ID extension reload를 명시 승인했다. 현재 source에는
read-only Shadow 후보만 준비했으며, exact-main CI와 LIVE precondition을 다시 확인한 뒤에만
배치·재로드한다. 상세 gate는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE2_READONLY_SHADOW_20261020.md`에 있다.

## 완료 — RCC Rebuild V1 2단계 Read-Only Shadow

source commit `a977a6f`의 CI 전체 통과 뒤 installed RCC payload를 exact backup
`D:\BCT\runtime\backups\rcc-rebuild-v1-stage2-exact-20261020-103204`으로 보존하고, Core
candidate 5개와 active 파일 4개를 source hash와 동일하게 배치했다. same-ID extension reload는
정확히 한 번만 요청했다. post-reload background build는
`2026-10-20-rcc-core-shadow-v1`, manifest는 `1.0.24`이며, `state.coreShadow`는
`READ_ONLY_SHADOW`로 Manager·Worker의 UUID, CONNECTED 상태와 `6:6:6` count를 기존 관측과
3회 연속 일치시켰다. 기존 content receiver도 read-only probe에 응답했다.

Native Host, Chrome 탭 새로고침/이동, Relay binding/storage, composer, 메시지 전송은 변경하지
않았다. 다음 3단계는 content protocol 호환성 전환으로 별도 승인 전에는 시작하지 않는다.

## 완료 — RCC Rebuild V1 3단계 content protocol 호환성

기존 `relay:activityProbe` content 응답과 background endpoint/Core Shadow 반영을
`test_core_shadow_protocol_v3.js`로 고정했다. LIVE에서도 두 고정 대화 receiver가 새 Shadow
build로 read-only probe에 응답했으므로 tab refresh 없이 protocol 호환성을 확인했다. 다음
4단계의 Manager→Worker 실제 원문 전송은 별도 사용자 승인 없이는 시작하지 않는다.

## 완료 — RCC Rebuild V1 3A단계 Source Relay 경계

Relay 계약을 `modules/rcc/extension/relay/contract.js`로 옮겨 Core와 Browser Adapter 사이의
독립 계층으로 고정했다. 이 계약은 UUID endpoint, 역할, operation ID, 원문만 다루며 Chrome,
DOM, storage, 전송과 효과 반복을 사용하지 않는다. 기존 `simple_relay_v0.js`는 compatibility
entrypoint이고, background loader는 canonical Relay contract를 직접 로드한다. source-only
검증은 `test_architecture_boundaries_v35.js`, `test_rcc_core_v1.js`, `test_simple_relay_v0.js`,
`test_core_shadow_protocol_v3.js`, baseline unittest 17개가 모두 통과했다.

설치본·확장 reload·Native Host·Chrome 탭·binding·storage·Composer·메시지 전송은 변경하지
않았다. `background.js`와 `content.js`의 실제 Browser Adapter 및 자동화/Legacy 기능은 아직
분리되지 않았으며, 4~7단계의 전환·차단·제거 대상이다. 세부는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE3A_SOURCE_RELAY_BOUNDARY_20261020.md`에 있다.

## 완료 — RCC Rebuild V1 4단계 Manager→Worker 단일 전송

새 Relay contract를 installed payload에 배치하기 전 exact extension backup(37 files, path/hash
mismatch 0)을 만들고 same-ID reload를 정확히 한 번 수행했다. 이후 Manager→Worker 원문 한 건은
Worker user turn 한 건만 추가했고 Worker는 새 assistant 응답을 완료했다. 기존 binding과 두
conversation UUID는 유지됐다. 탭 새로고침·이동·새 노드 생성은 하지 않았다.

## 완료 — RCC Rebuild V1 5단계 Worker→Manager 반환

기존 Native 결과는 false로 보고했지만, Manager UI에서 Worker의 새 응답 원문 `수신 확인`이
새 user turn으로 존재하고 그 뒤 Manager 응답이 생성된 것을 확인했다. 따라서 실제 반환은 한
번 전달됐으며 재전송하지 않았다. root cause는 virtualized DOM 총수에 의존한 상태 판정/영수증
표시 부족이며, source 보수는 exact submitted user turn에 route key를 연결하고 그 turn 내부
assistant 응답만 읽도록 바꾼다. compact receipt 상태도 Native 결과에 포함한다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE5_ROUTE_ADAPTER_REPAIR_20261020.md`에 있다.

## 완료 — RCC Rebuild V1 6단계 Legacy 변경 경로 차단

`legacy/command_policy.js`에서 새 Simple Relay·읽기 전용 조회만 허용하고, 기존 node/tab
관리·legacy send/wakeback·queue recovery·ACK·ACT·autoDirective·workerResult 같은 mutation
명령은 fail-closed로 거부하도록 source를 준비했다. remote CI `39357982486` 통과 뒤 exact
38-file backup(hash mismatch 0)을 만들고 policy/loader/background를 installed payload에 배치해
same-ID reload 한 번으로 활성화했다. `register`는 `NOT_APPLIED`와 explicit legacy-mutation
rejection으로 차단됐으며 전후 Manager/Worker state·binding은 동일했다. 탭 새로고침·이동·새
노드 생성·메시지 전송은 없었다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE6_LEGACY_BLOCK_20261020.md`에 있다.

## 완료 — RCC Rebuild V1 7단계 대화망 기반 (source-only)

고정 Manager/Worker를 권한 계층으로 확대하지 않고, 프로젝트 안의 대화창을 표시 이름,
사용자 관리 역할 태그, 안내용 활동 상태, 마지막 관측 사실로 표현하는 순수 대화망 계약을
추가했다. 역할 태그는 `구현`·`CI`·`병합`·`배포`·`조정`처럼 자유롭게 추가·삭제되는 추천
표지이며, 명시 대상 전달을 차단하거나 권한을 주지 않는다.

방향별 relay envelope도 source에만 추가했다. A→B 전달에는 처리 전문이 A로 돌아온다는
반환 안내를, B→A 반환에는 다음 전달서 또는 완료를 판단하라는 후속 안내를 붙인다. 원문과
안내문은 별도 스냅샷으로 보존된다. 새 대화창 생성·탭 이동·자동 실행은 이 단계에 포함되지
않고, legacy 탭 관리 기능도 제거하지 않았다. installed extension, reload, Native Host, Chrome
탭, storage, binding, 실제 메시지는 바꾸지 않았다. 세부와 검증은
`docs/exec-plans/completed/BCT_RCC_REBUILD_V1_STAGE7_CONVERSATION_NETWORK_FOUNDATION_20261020.md`에 있다.

## 완료 — BCT 대화망 1단계 durable Monitor snapshot (source-only)

RCC의 source 대화망 계약과 별개로 BCT durable store에 프로젝트·대화 UUID·안내용 역할 태그·
활동 상태·append-only Monitor snapshot을 추가했다. Monitor 원문 표기(예: `D1-3`)는 UUID와
함께 읽기 전용으로 저장하지만 BCT가 생성·해석·재형식화하지 않는다. `COMPLETE`, `PARTIAL`,
`UNAVAILABLE`을 구별하며 PARTIAL/UNAVAILABLE로 프로젝트 멤버나 이전 관측을 지우지 않는다.
Monitor에서만 보이는 노드는 자동 등록·자동 전달 대상이 아니다.

이 단계는 source SQLite schema/query와 unit test만 추가했다. BCT Control endpoint, Monitor
실시간 입력, RCC/Native Host/Chrome extension, 탭, storage, binding, 실제 메시지 및 LIVE
프로젝트 레코드는 변경하지 않았다. 세부 계약은
`docs/exec-plans/active/BCT_CONVERSATION_NETWORK_STAGE1_DURABLE_SNAPSHOT_20261020.md`에 있다.

## 완료 — BCT 대화망 2단계 BCT Control 읽기 조회 (source-only)

`bct_conversation_network_get(project="표시 이름")`를 MCP catalogue에 추가했다. 이 조회는
표시 이름·안내용 역할 태그·활동 상태·Monitor의 원문 표기/관측 상태·Monitor-only 노드만
반환한다. 사용자는 내부 project ID를 기억하지 않아도 되며, 대화 UUID/tab/window/session ID와
snapshot ID는 결과에 노출되지 않는다. 동일 표시 이름이 여러 개면 임의로 고르지 않는다.

실제 Monitor 호출·polling, relay, RCC/Native Host/Chrome extension, 탭, binding, storage, BCT
runtime 배포·재시작은 모두 변경하지 않았다. MCP 통합시험으로 임시 runtime에서 catalogue,
표시 이름 조회, `D1-3` 원문 표기, UUID 비노출을 검증했다. 세부는
`docs/exec-plans/active/BCT_CONVERSATION_NETWORK_STAGE2_READONLY_CONTROL_20261020.md`에 있다.

LIVE 반영 전 `bct_runtime_v1` file list에 `src/bct/conversation_network.py`가 빠진 것을 발견했다.
누락 상태에서는 새 MCP 도구가 runtime import에 실패하므로 배포하지 않았다. 파일을 exact release
목록에 추가했고, deployment service 12개 회귀시험과 MCP·대화망 시험으로 검증했다.

## 진행 — RCC Simple Relay V0 LIVE 단일 전달

RCC extension 1.0.22는 기존 orchestration role registry와 분리된 `simple-relay-bind` /
`simple-relay-send` 경로를 포함한다. Manager·Worker의 exact conversation UUID 관계만 binding으로
저장하며, send는 `from=manager|worker`, 원문, operation ID만 사용한다. 탭·창·세션·임시
노드·자동 회수·자동 재시도는 이 경로에 없다. 2026-10-20에 canonical installed payload를
`D:\BCT\runtime\backups\rcc-extension-20261020-090800`으로 백업한 뒤 재로드했고, build
`2026-10-20-simple-relay-return-v0`의 Manager→Worker 원문 한 건이 `SUBMITTED`로 확인됐다.
Worker는 정확히 한 user turn과 한 assistant turn을 추가한 뒤 IDLE이 됐고, 그 새 Worker 응답
원문은 Manager에 한 번 `SUBMITTED`로 전달됐다. 반환은 source send receipt의 pre-send
assistant count보다 새 응답이 늘었을 때만 가능하며, 이전 1.0.22 receipt처럼 그 증거가 없는
항목은 전송 없이 거부한다. Core adapter는 source head
`7df4f06a5e9390175392e341e567b02631fa6ce5`, generation 160으로 LIVE 배포됐다.

## 완료 — RCC Native Host 보안 경계 배포 정합화

2026-10-20에 Chrome Native Messaging 등록값을 canonical manifest
`D:\ChromeExtensions\RCC\native\com.ai_workspace_relay.host.json`로 정정했다. 재로드 뒤
기존 host executable이 구식 pipe DACL로 떠 Core의 `DACL_ACE_COUNT` 검증에 거부되는
배포 불일치를 확인했다. 현재 source의 hardened `RelayNativeHostV2.cs`를 .NET Framework
compiler로 빌드해 canonical executable에 배포했고, 이전 executable과 manifest는
`D:\BCT\runtime\backups\rcc-native-host-20261020-084900`에 보존했다. 실행 host를 재연결한
뒤 RCC `state` 요청이 `ok: true`로 성공하고, 고정 Manager와 Worker의 exact conversation
identity가 모두 state에 보이는 것을 확인했다. 이 검증은 읽기 전용이며 채팅 메시지를
전송하지 않았다.

## 보류 — 병목 신호 기반 Instant ACK 대조 V0

`bottleneck_ack`는 RCC의 exact tab telemetry에서 한 고정 대화가 연속 생성 중인
시간을 읽고, 임계값을 넘으면 **별도의 ACK 전용 대화**에만 고정된 Instant ACK
대조 문구를 한 번 전송하는 opt-in Core 계층이다. 생성 중인 원 대화에는 입력을
넣을 수 없고 작업 문맥을 오염시키므로 source/probe가 같으면 정책 로드 자체가
실패한다. 직접 탭의 현재 session/tab/window/conversation identity를 직전 snapshot에서
다시 얻어 기존 `relay_browser` receipt로 제출하며, 같은 generation onset은 operation
ID와 in-process latch로 중복 전송하지 않는다. UNKNOWN/미확인 결과는 자동 재시도하지
않는다. probe의 generation start/finish가 제출 뒤에 관측되면 시작·완료·생성 시간을
`bct_status`의 `core.bottleneck_ack`에만 수치로 기록한다.

초기 LIVE 수락시험과 보완 코드는 감사용으로 보존했지만, 사용자의 현재 협업 흐름과
무관하게 자동 메시지를 보내지 않도록 정책을 `enabled=false`로 전환했다. 다시 쓰려면
별도 사용자 요청과 분리된 진단 계획이 필요하다. focused unittest 16개, `compileall`,
`git diff --check`는 통과했다. 전체 suite는 이 환경의 30초 실행 창에서 완료 결과를
받지 못했으므로 통과로 기록하지 않는다.

## 정의 — 고정 Manager↔Worker 자연어 릴레이 V0

목표는 대화를 자동으로 판단·구조화·대체하는 것이 아니라, 사용자가 하던 전달을
안전하게 자동화하는 것이다. BCT는 고정된 Manager와 Worker 대화를 역할·exact 대화
identity로 등록하고, 전달 전문을 바꾸지 않은 채 정확한 상대에게 보내며 delivery
receipt만 남긴다.

- Manager는 필요할 때 자연어 전달서를 작성한다. BCT는 목표·할 일·완료 조건 양식을
  강제하거나 Worker 생성 여부를 판단하지 않는다.
- `Manager → Worker`는 전달서 원문과 source/target identity, 제출·전달 결과를 receipt로
  남긴다. Worker는 원문을 보고 기존 대화 문맥 안에서 처리한다.
- `Worker → Manager`는 Worker의 처리 결과 전문을 그대로 되돌린다. Manager는 그 결과를
  보고 다음 전달서 또는 완료를 스스로 결정한다.
- V0에는 자동 재질문, 자동 재전송, 자동 노드 생성, ACK·병목 감시, 작업표 강제 및
  결과 요약/변형이 없다. 전송 후 결과가 불명확하면 `UNKNOWN`으로 남기고 재전송하지
  않는다.

완료 판정은 전달 왕복 하나에 대해 source/target 대화 identity, 제출 receipt, 실제
대화에 나타난 원문 및 응답 전문이 일치하는지로만 한다. Manager의 판단 품질은 BCT의
검증 대상이 아니다.

## 완료 — UNKNOWN 계측·RCC payload 판정

tunnel-client v0.0.16의 독립 one-shot 전환, Supervisor 자동 복원, Hosted read timing은
완료됐다. RCC PR #226 `background.js`도 실제 설치본과 main source의 SHA-256이 일치하고,
재로드 뒤 두 RCC 인스턴스가 같은 build ID로 OPEN이다. 고정 SHA 문구 대신 현재 값은
`origin/main`, `runtime\current.json`, Core health 및 파일 해시로 다시 확인한다.

공통 operation effect-stage journal과 안전한 `claim_reconcile`이 LIVE다. read-only 9건,
CreateProcess 이전 FileNotFound execute 4건, 광범위 relay 2건, 무전송 orchestration 1건의
Claim을 증거로 정리했다. 원래 UNKNOWN receipt는 감사 기록으로 보존한다. 남은 Claim은
실제 전송·실행 가능성을 배제할 수 없는 정확한 과거 자원에만 묶여 있으며 재전송하거나
강제 해제하지 않는다. Monitor는 `SHARED_RESOURCE`와 `EXACT_RESOURCE`를 분리하고 RCC
source/live payload SHA·일치 여부를 직접 표시한다. 불일치는 자동 재로드·재전송하지 않고
배포 차단 및 진단 신호로만 사용한다.

공유 LIVE 변경은 대상별로 정확히 하나의 Work만 소유한다. 타이머·채팅·스크립트는 별도
소유자가 아니라 exact operation/payload/pre-state/expiry에 묶인 executor다. 주기적 채팅
감시 대신 이벤트 또는 짧은 조건부 local one-shot을 사용하고, 결과와 postcondition을
기록한 뒤 소유권을 종료한다. 상세는
`docs/exec-plans/active/BCT_TUNNEL_V016_CUTOVER_20261019.md`에 있다.

## 완료 — Unicode desktop clipboard

`desktop_clipboard`의 BCT/VTL 구현, CI, exact-main 배포와 LIVE 수락시험이 끝났다.
`get`/`set` 모두 exact Session Lease와 emergency-stop fence를 요구한다. VTL Agent 2.2는
STA `UnicodeText` API를 사용해 Windows UTF-8 시스템 로캘 on/off와 독립적으로 동작하며,
set은 재읽기 exact match 전에는 성공으로 확정하지 않는다. BCT durable evidence에는
Unicode scalar/UTF-8 byte 길이와 SHA-256만 남고 원문은 최초 성공 `get` 응답에만 붙는다.
VTL PR #47과 BCT PR #228/#229가 required CI를 통과해 병합됐고, BCT Generation 141은
39개 MCP 도구에 `bct_desktop_clipboard`를 포함한다. Agent 직접 및 인증 MCP LIVE에서
한글+보조 평면 문자의 set/get/hash를 확인하고 직전 클립보드를 복원했다. 최종 Lease는
null이고 emergency stop은 false다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_CLIPBOARD_20261019.md`에 있다.

## 완료 — 로그인 세션 Desktop Agent 자동 복구

Desktop Session Agent는 boot service가 아니라 로그인 사용자의 interactive session에
존재해야 화면·창·입력을 정확히 제어할 수 있다. VTL의 `BCT Desktop Session
Supervisor`가 immutable VTL release·manifest·Agent-start source를 검증하고 동일
세션의 exact Agent만 재사용하거나, 종료된 Agent만 복구한다. old/foreign release는
임의 종료하지 않고 mismatch로 남긴다. Scheduled Task는 `LogonTrigger`,
`InteractiveToken`, `LeastPrivilege`로 실행되며, 관리 권한은 Task Scheduler 등록
갱신 때만 필요하다.

LIVE에서 활성 Lease 없음 및 emergency stop 해제 상태의 구형 Agent를 한 번 종료했고,
Supervisor가 current immutable release의 새 Agent로 자동 복구했다. 이후 BCT control
status는 interactive input desktop, null lease, clear emergency stop을 반환했다. 현재
실제 release는 VTL `current.json`, Agent endpoint와 Supervisor receipt로 확인한다.
상세는 VTL의
`docs/exec-plans/completed/bct-desktop-session-supervisor-20261019.md`에 있다.

## 완료 — bounded desktop scroll/drag

`desktop_input`은 기존 exact Window Lease 아래에서 wheel `scroll`과 좌클릭
`drag`를 제공한다. scroll delta와 drag 단계/경로가 제한되며 foreground, 비가림
좌표, Lease, 프로세스 생성 시점, Session/virtual desktop, emergency stop을 실행
직전에 다시 검증한다. VTL Agent 전체 probe와 BCT 집중/분할 CI, exact-main 배포,
인증 MCP disposable-probe 수락시험이 통과했다. 최종 Lease는 null이고 emergency
stop은 false다. 현재 SHA와 generation은 `origin/main`, 두 `runtime\current.json`,
health `release_sha`로 확인한다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_SCROLL_DRAG_20261019.md`에 있다.

## 완료 — Chrome 웹 콘텐츠 exact 제어 V1

`desktop_chrome_content_list`와 `desktop_chrome_content_action`을 LIVE 배포했다.
목록은 정확한 Chrome HWND의 한 visible `RootWebArea`에서 edit/button 메타데이터만
읽고 field value는 반환하지 않는다. 동작은 기존 Window Lease, document title,
활성 tab ordinal/full title, opaque element ID를 모두 재검증한 뒤 ValuePattern set 또는
InvokePattern invoke를 실행한다. LIVE에서 UIA ValuePattern이 background Chrome을
활성화하는 사실이 확인되어 `set_value`는 exact leased 창이 이미 foreground일 때만
허용하고 필요 시 기존 `desktop_window_activate`를 명시적으로 먼저 쓴다. InvokePattern은
foreground 불변일 때만 성공한다. foreground 변경·Lease 손실·호출 후 불명확 결과는
UNKNOWN이며 자동 재시도하지 않는다. text는 raw evidence/output에 넣지 않고 UTF-8
문자/byte 길이와 SHA-256만 남긴다.

VTL PR #37/#38/#39/#40, BCT PR #221/#222와 모든 required CI가 통과했다.
BCT full suite 789개와 focused 61개 테스트도 통과했다. 완료 당시 VTL
immutable main의 Agent 2.0.2와 BCT exact main이 배포됐다. 현재 버전은 고정 SHA
문구를 신뢰하지 않고 각 `origin/main`, VTL/BCT `runtime\current.json`, health
`release_sha`를 기계적으로 비교한다. 완료 당시 health는 READY/OK였고 MCP
catalogue는 두 새 도구를 포함한 38개였다.

인증 MCP LIVE에서 background write는 실행 전 확정 실패했고, 명시적 활성화 뒤
16자/20 UTF-8 byte marker set 및 빈 문자열 clear가 각각 matching length/hash와
`foregroundPreserved=true`로 APPLIED됐다. 후속 조회는 빈 입력을 확인했다. 전용
Chrome for Testing 창은 다시 최소화했고 원래 foreground를 복원했으며 최종 Lease는
null, emergency stop은 false다. 상세 증거는
`docs/exec-plans/completed/BCT_CHROME_CONTENT_CONTROL_20261019.md`에 있다.

## 완료 — Windows UTF-8 설정 독립 VTL 실행

Windows의 **유니코드 UTF-8 사용** 시스템 로캘은 게임/프로그램 호환을 위해 켜거나
꺼도 된다. BCT/VTL은 이 전역 설정을 바꾸거나 재부팅을 요구하지 않는다. VTL의
기계 판정은 명시적 UTF-8 JSON 파일을 사용하고, BCT는 자식 stdout/stderr를 bytes로
받은 뒤 UTF BOM, strict UTF-8, CP949, 현재 Windows ANSI/OEM 순으로 진단 로그만
해석한다. 자식 Python에는 process-local UTF-8 환경만 준다. 구현·focused test는
통과했다. VTL PR #21/#22와 BCT PR #206이 병합됐고, exact main runtime
sync/prewarm와 BCT exact-SHA 배포가 완료됐다. source `origin/main`, 로컬 source,
runtime `current.json`과 health `release_sha`는 최종 점검 때 기계적으로 비교한다.
인증된 LIVE `bct_vtl_validate`와 duplicate receipt도 PASS했다. 상세는
`docs/exec-plans/completed/BCT_VTL_DIRECT_VALIDATION_20261019.md`를 따른다.

## 완료 — 일반 ChatGPT의 직접 VTL-first 검증

목표는 일반 ChatGPT/Codex의 반복 개발 검증을 로컬 BCT + VTL Fast mode에서 끝내고,
통과한 한 후보만 GitHub에 올려 required CI를 최종 1회 수행하는 것이다. 실패 후보마다
Actions를 디버깅 루프로 사용하는 방식은 피한다. 변경 범위에 따라 정적 검사/focused test,
VTL browser/GUI scenario, Full/VM E2E 순으로 가장 싼 충분한 tier를 선택한다.

새 `vtl_validate` capability는 `D:\TOOLS\VTL\current.json`의 immutable release manifest 전체를
검증하고, work scope 안의 browser 또는 profile scenario를 background operation으로 직접 실행한다.
VTL SHA, 입력 SHA, PASS/FAIL/TIMEOUT, 외부 evidence/result 경로가 BCT receipt에 남으며 GitHub
Actions를 dispatch하지 않는다. VTL runtime installer와 외부 evidence/run-ID 계약은 VTL 저장소가
소유한다. VTL PR #18과 BCT PR #203의 exact-head/main CI가 통과했고 해당 BCT
merge가 LIVE generation 121로 배포됐다. 최종 설치 VTL PR #20 main은 한글 사용자 경로를
비대화형 Windows 코드페이지와 무관하게 처리하고, browser cold prepare/Fast selftest가
PASS한 뒤에만 runtime pointer를 공개한다. 인증된 MCP operation
`bct-vtl-direct-live-af1c4fd9-6e75ab68-browser-fast`는 이를 직접 실행해 `APPLIED / PASS`를
반환했다. 같은 operation ID의 재호출은 원 영수증을 반환했고 VTL GitHub workflow는 새로
생성되지 않았다.
일반 ChatGPT는 BCT Control이 새 catalogue를 읽은 세션에서 이 진입점을 사용할 수 있다. 상세는
`docs/exec-plans/completed/BCT_VTL_DIRECT_VALIDATION_20261019.md`를 따른다.

## 완료 — 일반 ChatGPT/Codex의 VTL Desktop Session 공동 사용 계약

일반 ChatGPT 대화도 BCT Control 연결과 현재 MCP catalogue가 실제로 제공되면
VTL Desktop Session Agent를 사용할 수 있다. 실시간 데스크톱 진입점은 BCT Control
MCP이며, GitHub Actions의 VTL workflow는 exact-SHA 검증을 남기는 별도 경로다.

읽기 전용 status/capture/window list는 병행 가능하다. 입력·창 활성화·프로그램
실행은 기존 세션당 단일 Lease가 직렬화하며, 각 대화는 고유 work ID와 짧은 Lease를
사용하고 완료 즉시 반납한다. Lease 충돌 시 대기·보고하고 타 owner의 Lease를
빼앗거나 emergency reset으로 우회하지 않는다. Emergency stop은 전역 중지이고,
UNKNOWN 효과는 무재시도 후 receipt와 화면으로 화해한다. 일반 대화에 전달할 전체
운영 절차는 `docs/USER_GUIDE.md`의 "일반 ChatGPT와 Codex가 데스크톱을 함께
사용할 때" 절에 기록했다.

## 완료 — Lease로 제한된 창 상태·위치 제어

BCT LIVE는 `desktop_window_manage`로 활성 Window Lease에 묶인 정확한 창을
복원·최소화·최대화·이동/크기 변경할 수 있다. 효과 직전에 owner/Lease ID,
HWND/PID/process birth, Session, virtual desktop 및 emergency stop을 다시
검증한다. 창 닫기는 사용자 데이터 손실 경계라 제공하지 않는다.

VTL PR #25와 BCT PR #208의 exact-head/main CI, immutable VTL Agent 1.5 배포,
BCT exact-main 배포 및 인증 MCP LIVE 수락시험이 완료됐다. LIVE 시험은 BCT로
프로브를 실행·바인딩하고 네 상태 동작과 이동/크기 변경, 활성화, 입력을 영수증으로
검증한 뒤 Lease·프로세스·임시 파일을 정리했다. 검증 wrapper는 durable receipt의
`programLaunch.pid`를 사용하고 원자적으로 교체되는 probe JSON 읽기의 일시적인
Windows 공유 오류를 재시도해야 한다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_WINDOW_MANAGE_20261019.md`에 있다.

## 완료 — 로그인 세션 프로세스·파일 진입점 탐색

BCT LIVE의 읽기 전용 `desktop_explore`는 실제 Desktop Session Agent와 같은
Session의 프로세스를 PID/process birth/실행 파일 경로/현재 가상 데스크톱 창에
연결하고, 로그인 사용자의 알려진 폴더와 준비된 드라이브를 반환한다. Lease나
foreground 변경 없이 여러 대화가 병행 조회할 수 있다.

파일 내용과 폴더 순회는 이 기능에 중복 구현하지 않았다. 발견한 경로를 Work root로
명시한 뒤 기존 `read`의 bounded `directory_tree`/file을 사용하므로 기존 scope와
reparse-point 차단이 그대로 적용된다. VTL PR #27, BCT PR #210, Agent 1.6 rollout,
exact-main 배포와 인증 MCP LIVE 조합 검증이 완료됐다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_EXPLORE_20261019.md`에 있다.

## 완료 — Chrome/Explorer 의미 기반 창 선택·바인딩

BCT LIVE의 `desktop_application_target`은 Chrome과 Explorer를 정확한 process
family와 top-level window class로 분류하고, 선택적으로 Unicode 창 제목으로
좁힌다. `list`는 읽기 전용이고, `bind`는 현재 Session/virtual desktop 후보가
정확히 하나일 때만 기존 Window Lease를 발급한다. 후보 0개·여러 개·Agent 목록
truncation은 제어 효과 전에 실패하므로 좌표나 PID 추측으로 다른 창을 잡지 않는다.

BCT PR #212의 exact-head/main CI, generation 128 exact-main 배포와 인증 MCP LIVE
수락시험이 완료됐다. LIVE에서는 Chrome 3개와 Explorer 0개를 분류하고 고유한
Chrome 창을 HWND/PID/process birth/Session/virtual desktop fingerprint로 bind한
뒤 활성화나 입력 없이 Lease를 즉시 반납했다. Chrome 탭/프로필 연결은 아래의 별도
increment로 완료됐다. 상세는
`docs/exec-plans/completed/BCT_DESKTOP_APPLICATION_TARGET_20261019.md`에 있다.

## 완료 — Chrome 프로필·탭 의미 기반 선택·바인딩

Agent 1.8.1은 기존 Chrome 창을 UI Automation으로 읽어 제한된 프로필 라벨,
탭 제목과 현재 선택 탭을 반환한다. URL은 반환하지 않는다. BCT의
`desktop_application_target`은 `profile_query`, `tab_title_query`,
`tab_scope`(`active`/`any`)로 좁히고, UIA 불완전·0/복수 후보·window/tab
truncation이면 bind 전에 실패한다. list/bind 모두 Chrome을 실행·종료·활성화하거나
입력하지 않는다.

초기 Agent 1.8.0 LIVE에서 helper UTF-8 stdout을 Windows 코드페이지로 해석하는
오류가 발견됐고 fail-closed했다. VTL PR #32가 strict UTF-8 자식 스트림과 강한
응답 검증을 추가했다. 정확한 완료 당시 SHA는 아래 완료 증거 문서에 보존하고,
현재 상태는 각 `origin/main`, runtime `current.json`, health `release_sha`를 기계적으로
비교해 판정한다.
인증 MCP LIVE는 Chrome 4개 중 Unicode 프로필+현재 탭 조합으로 1개를 bind/release했고,
기존 Chrome PID/process birth/HWND는 모두 보존됐으며 최종 Lease는 null,
emergency stop은 false였다. 상세는
`docs/exec-plans/completed/BCT_CHROME_SEMANTIC_TARGET_20261019.md`에 있다.

## 완료 — foreground를 보존하는 Chrome exact-tab 전환

BCT LIVE의 `desktop_chrome_tab_select`은 기존 Chrome Window Lease와 정확한
HWND/PID/process birth/Session/virtual desktop, ordinal 및 방금 관측한 전체 탭
제목에 묶여 한 탭만 전환한다. VTL Agent는 UIA 선택 호출 대신 exact client HWND에
제한된 window message를 보내며 전후 foreground가 같음을 확인한다. 탭을 열거나
닫거나 이동하지 않고 URL도 다루지 않는다.

초기 UIA 구현이 background 창을 foreground로 올린 실제 결함은 UNKNOWN으로
차단됐고, 원래 탭과 foreground를 별도 보상했다. 새
`desktop_chrome_tab_reconcile`은 동일 work/principal의 정확한 changed-foreground
UNKNOWN에 한해 no-Lease/no-stop, exact foreground/window/active-tab 상태를 읽기
전용으로 증명한 뒤 그 claim만 해제한다. 과거 Work는 새 action을 추가할 수 없으므로
원래 `desktop_chrome_tab_select` 권한에서만 이 좁은 화해 권한을 파생한다.

Chrome 접근성 제목의 메모리 수치는 변하므로 전체 제목은 fresh inventory 직후
소비한다. 활성 탭을 바꾸면 top-level 창 제목도 바뀌므로 복구 조회에 이전 창 제목
필터를 유지하지 않는다. exact-main CI/배포, 과거 UNKNOWN 화해, background 실제
전환과 원복, foreground/프로세스 보존 및 최종 무Lease/무래치 상태까지 완료했다.
상세와 정확한 완료 증거는
`docs/exec-plans/completed/BCT_CHROME_TAB_SELECT_20261019.md`에 있다.

## 완료 — Explorer 실제 폴더 경로 선택·바인딩

`desktop_application_target`의 Explorer 경로는 기존 로컬 폴더의 절대
`folder_path`를 받아 Agent 1.7의 Shell 위치와 정확한 HWND/PID/process birth/
Session/current virtual desktop fingerprint를 결합한다. 상대 경로·없는 폴더는
거부하고 가상 Shell 위치는 로컬 경로로 추측하지 않는다. 목록은 읽기 전용이며
bind는 후보가 정확히 하나일 때만 기존 Window Lease를 발급한다.

VTL PR #29와 BCT PR #214, 양쪽 CI, exact-main immutable VTL runtime/Agent 1.7,
BCT generation 130 배포 및 인증 MCP LIVE exact-list/bind/release 수락시험이
완료됐다. 최종 제어 상태에는 Lease와 emergency-stop latch가 없다. Chrome
탭/프로필 식별도 위 별도 increment로 완료됐다. 상세는
`docs/exec-plans/completed/BCT_EXPLORER_PATH_TARGET_20261019.md`에 있다.

## 완료 — Adaptive CI와 VTL exact-SHA 데스크톱 스모크

BCT PR #199는 보수적 변경 범위 판정, 정확 중복 unittest 제거, 네 개의 결정적
가중 샤드, 독립 browser-bridge gate를 추가했다. 알 수 없는 실행 경로는 core와
browser 전체 검사로 fail closed하며 문서-only 변경만 경량화한다. 발견된 751개
인스턴스 중 같은 test ID·class·method·instance state인 import 재노출 184개만
제거했고, 567개 고유 테스트를 정확히 한 번씩 실행한다.

검증된 BCT 구현 commit `f9b299d`는 CI run
`39169773634`에서 scope/preflight/core 4-shard/browser Windows E2E를 모두
통과했다. 전체 벽시계는 211초로 이전 직렬 workflow 약 674초보다 약 69%
줄었다. VTL repo의 Session 1 runner는 같은 BCT SHA를 별도 checkout하여 run
`39169787101`에서 status/capture/monitor/windows read-only smoke를 18초에
통과했다. launcher fail-fast build 산출물은 package-purity 검사 전에 launcher
root 아래 `bin/obj`만 bounded cleanup하고 Windows E2E 전에 재빌드한다.

BCT에는 self-hosted runner나 cross-repo Actions credential이 없으므로 VTL 검증의
자동 dispatch는 아직 하지 않는다. 현재는 VTL 소유 수동 exact-SHA workflow가
GitHub 증거를 남긴다. 자동화하려면 사용자 승인 아래 별도 BCT Session 1 runner
등록 또는 최소 권한 GitHub App/fine-grained token 중 하나를 선택해야 한다.
런너 identity나 credential을 임의 변경하지 않는다. 상세 증거는
`docs/exec-plans/completed/BCT_ADAPTIVE_CI_V1_20261019.md`에 있다.

## 완료 — 제한된 프로그램 실행과 새 PID 창 바인딩

BCT LIVE는 인증된 `desktop_program_launch`를 제공한다.
활성 `session` Lease 아래에서 존재하는 절대 비-reparse `.exe`와 bounded
문자열 인수 배열만 `UseShellExecute=false`로 실행한다. 새 PID/process birth/
Session을 기록하고 그 PID가 현재 가상 데스크톱에 만든 보이는 최상위 창을
입증할 때만 같은 Lease를 정확한 창 fingerprint로 원자적으로 승격한다.

창 대기 중 전역 control lock을 잡지 않아 긴급정지는 독립적으로 호출할 수
있고, 나머지 Lease 효과는 transition marker로 차단된다. 실행 뒤 transport가
불명확하면 UNKNOWN으로 남기며 재시도하지 않는다. 새 PID 소유 창이 없으면
실행은 APPLIED이지만 unbound로 반환한다. Chrome singleton처럼 기존 프로세스로
넘기는 앱을 임의로 바인딩하지 않는다.

VTL PR #14와 BCT PR #197의 CI, Agent 1.4 exact-source rollout, BCT exact-main
배포와 인증 MCP LIVE E2E가 통과했다. LIVE E2E는 다른 work 거부, 활성화,
한글 입력 실제 관측, 긴급중지/리셋 및 최종 무리스/무래치 상태까지 확인했고
프로브와 임시 파일을 제거했다. 완료 증거는
`docs/exec-plans/completed/BCT_DESKTOP_PROGRAM_LAUNCH_20261019.md`에 있다.

다음 데스크톱 parity 경계는 프로세스·파일 탐색, Chrome/Explorer의 상위 수준
workflow, 창 닫기 또는 Chrome의 process-family/profile-aware 바인딩 중 하나로
별도 설계한다. 이번 경계에 임의 shell, 자동 로그인이나 Scheduled Task를 섞지
않는다.

## 완료 — 현재 세션 정확한 창 목록·활성화

BCT LIVE는 현재 가상 데스크톱의 보이는 최상위 창을 exact fingerprint로
조회하고, 활성 `window` Lease에 묶인 숨김/최소화되지 않은 정확한 창만
foreground로 활성화할 수 있다. owner/lease, HWND/PID/process start, Session,
virtual desktop, 긴급정지를 효과 직전에 재검증하며 UNKNOWN은 재시도하지
않는다. 프로그램 실행과 창 상태·위치 제어도 이후 별도 완료됐다.
완료 증거는
`docs/exec-plans/completed/BCT_DESKTOP_WINDOW_CONTROL_20261019.md`에 있다.

## 현재 작업 — 신뢰된 다중 ChatGPT 협업 정상화

보호 경로 이전보다 실제 Manager → Worker 협업을 우선한다. 운영 기준은 계속
`D:\BCT`이며 `%LOCALAPPDATA%` 또는 `BCT-Protected` 이전은 협업의 선행 조건이
아니다. 기존 보호 경로 소스와 영수증은 보존하지만 현재 본류에서는 보류한다.

- 기존 Principal/Work/Policy는 프로젝트 범위와 사용자 목표를 한 번 묶는 경계로
  유지한다. 현재 Policy의 일반 개발 작업은 이미 반복 승인 대상이 아니다.
- epoch/lease/Claim, exact attachment, ACK/receipt, UNKNOWN 무재전송은 충돌·중복·
  잘못된 대화 전달을 막는 정합성 계약이므로 유지한다.
- 정적 Schema 2 Work allowlist는 새 Work마다 설정·배포를 요구하는 실제 병목이라
  제거한다. 전역 스위치는 비상 정지용으로 유지하고, ON 이후 새로 시작한 세션만
  `RCC_RESULT_POLL_V1`로 SQLite에 고정한다. 기존 세션은 migration 기본값
  `LEGACY_RETURN_V1`을 유지하여 과거 Wake/UNKNOWN을 재해석하지 않는다.
- Worker assignment는 `read` 전용에서 프로젝트 범위의 일반 개발 작업으로 넓힌다.
  deploy/service control/credential/delete/브라우저 제어 같은 고위험 작업은 자동
  Worker 범위에 포함하지 않는다.
- 최종 완료 판정은 PR/CI가 아니라 새 격리 Work에서 Manager 1 + Worker 2의 실제
  결과 영속화, 종합, FOLLOW_UP, COMPLETE, ACK, 중복 방지 및 Manager 교체 복구가
  성공한 뒤에만 내린다. LIVE 변경과 Chrome 메시지 전송은 묶은 운영 승인 후 한다.

세부 계약은
`docs/exec-plans/active/BCT_TRUSTED_COLLABORATION_NORMALIZATION_20261017.md`를 따른다.

## 중단 작업 — 보호된 운영 경로 이전

사용자 결정으로 `%LOCALAPPDATA%\BCT`/`BCT-Protected` 이전과 추가 ACL 강화는
중단했다. 운영 정본은 `D:\BCT` 하나이며 `bct.toml`에서도 보호 runtime을 활성
배포 프로필로 제공하지 않는다. 이미 만든 일반화된 보호 경로 코드·격리 테스트,
독립 worktree와 기존 영수증은 감사 자료로 보존하지만 협업 활성화의 선행 조건이나
현재 실행 계획으로 사용하지 않는다. LIVE·Registry·ACL·RCC/Chrome에는 역이전이나
추가 변경을 수행하지 않는다.

## 현재 작업 — Durable Orchestration PR C (DRAFT 준비, 운영 비활성)

PR A #149와 PR B #150이 병합된 최신 검증 main에서 독립 worktree로 PR C를 구현했다.
PR B의 영속 `orchestration_dispatch_outbox`를 기존 RCC Worker 전송·PR2 상태
계약에 연결하고, 결과 커밋 뒤 생성되는 Manager Wake도 같은 단일 dispatcher가
이벤트 우선/2초 bounded polling으로 전달한다.

- Worker 전송은 exact attachment/epoch/generation/Policy/lease를 실제 pipe write
  직전에 재검증한다. write 호출이 시작된 뒤 오류는 항상 UNKNOWN이며 재전송하지 않는다.
- RCC 제출 ACK, Worker `RESULT_PERSISTED`, PR2 최종 ACK, RCC result-ack은 서로
  다른 상태다. exact receipt와 JS/Python resultHash 일치 뒤에만 Assignment 완료,
  Manager Wake, PR2 ACK를 한 SQLite transaction으로 확정한다.
- Manager Wake는 pipe-open 전에는 PENDING이다. 실제 write 직전 callback에서만
  Work/Manager epoch/lease/attachment/dispatcher fence를 검증하고 DELIVERING으로
  claim한다. UNKNOWN Wake는 결과 조회만 하며 재전송하지 않는다.
- Outbox와 Wake는 한 dispatcher lease의 독립 keyset cursor로 공정하게 순환한다.
  앞선 8개 RCC 장애가 9번째 Wake를 굶기지 않는 회귀를 포함한다.
- 격리 focused 82 PASS, 전체 558 PASS, compileall/diff check PASS,
  pre-commit 독립 감사 P0/P1/P2 없음. 정확한 Draft PR/CI는 push 후 기록한다.
- RCC RESULT_PERSISTED의 신뢰된 즉시 push는 아직 없다. 이벤트는 Core 내부 commit
  signal이고, RCC 결과 발견은 bounded polling 복구 경계다.
- RCC Named Pipe의 실제 Windows DACL/서비스 주체 제한은 아직 실증되지 않았다.
  따라서 `DEPLOYMENT_BLOCKED`; Schema 2 기본 OFF, LIVE/서비스/RCC/Chrome 변경 금지다.
- 공유 `D:\BCT\source`, PR3-o 미커밋 작업, stash, Issue #111,
  기존 UNKNOWN/Claim/consumed_at과 과거 영수증은 건드리지 않았다.

상세 계약과 테스트 행렬은
`docs/exec-plans/active/BCT_DURABLE_ORCHESTRATION_PR_C_20261016.md`를 따른다.

## 현재 작업 — Issue #111 manager wakeback (LIVE_DEPLOYED, hosted E2E ACCEPTED)

Manager wakeback V1은 PR #112로 main에 병합되어 exact-SHA LIVE 배포까지 완료했다.
이후 BCT Control을 새로고침해 hosted `bct_orchestrate` 가용성도 확인했다. 첫 신규
manager→worker→manager wake E2E는 기존 LIVE나 기존 UNKNOWN/claim을 변경하지 않고
시도했으나, 공유 RCC instance fence 때문에 새 assignment나 browser delivery 전에
안전하게 중단했다.

- 알려진 terminal worker result와 같은 SQLite transaction에 immutable manager-wake
  intent를 저장한다. RCC 전송 실패가 worker result를 재실행하거나 지우지 않는다.
- wake는 manager epoch, exact attachment generation, RCC instance/session, tab,
  conversation, relay role, binding receipt 및 deterministic delivery ID로 fence한다.
- manager takeover 시 이전 `PENDING` wake는 `STALE`로 남고, 새 manager attachment로
  별도 epoch event만 생성한다. `DELIVERING`/`UNKNOWN`은 외부 효과가 불명확하므로
  자동 재통지하지 않는다.
- RCC `send-wakeback`은 더 이상 `returnTo`를 `WORKER`로 바꾸지 않고 호출자가 준
  exact manager role을 보존한다. RCC candidate는 1.0.20 / build
  `2026-10-15-rcc-manager-wakeback-v13`이다.
- Local gates: `python -m unittest discover -s tests -v` **193 PASS**,
  `python -m compileall -q src tests`, `git diff --check`, RCC source/Node
  regression all PASS. PR #112 passed BCT CI run `38616742752` and its merged
  source is the generation-85 LIVE Core release.  Verify current source/runtime
  identity through `origin/main`, local `HEAD`, `current.json.source_head`, and
  `/health.release_sha`; do not treat this handoff as a live SHA authority.

새 무해한 target에서의 단일 worker 결과 → durable manager wake는 검증됐다.
`issue111-wake-e2e-86ea3a2-01`은 fresh exact attachments에서 worker
`APPLIED`, manager wake `DELIVERED`를 기록했다. 기존 UNKNOWN은 재전송하지
않았다. 다만 최초 post-refresh preflight는 ACTIVE `BCT-ISSUE111-LIVE-20261015`와 UNKNOWN
`rcc-localbridge-rename-tab594833023-20261015-02`가 같은
`rcc-instance:6174664e1c1b4e6db1d4729c841db3c9` resource를 점유한 것을 확인했다.
새 E2E의 node-sync도 이 shared resource를 claim하므로, 충돌 상태에서 실행하지
않았다. 이 UNKNOWN/claim 또는 ACTIVE work를 재전송·해제·takeover·재사용하지 말고,
read-only evidence와 canonical reconciliation이 안전한 fresh target을 허용할 때만
재개한다.

## 현재 검증 상태

Durable Orchestration is not yet LIVE accepted. Follow the current-gate section
of `docs/exec-plans/active/BCT_DURABLE_ORCHESTRATION_V1.md`: freeze features;
single roundtrip -> durable recovery -> one manager/worker -> multi-worker and
manager takeover. Preserve historical UNKNOWN/claims. PR #105 fixed retirement
of an already-persisted submitted bootstrap record at the real next-dispatch
entry path. Exact-head/main CI, deployment, one existing-tab roundtrip and
post-reload durable receipt retrieval passed. The next single manager/worker
attempt submitted once but ended UNKNOWN during response capture.

READ-only DOM evidence identifies a concrete routed-turn matching defect:
the collapsed long user-message wrapper adds an aria-hidden ellipsis outside
the actual message body. RCC includes it in textContent, so the exact 1,244-char
prompt becomes 1,245 chars and ROUTE_TURN_NOT_RESOLVED follows. The worker's
matching result is visible, but is not promoted to an accepted receipt. The
separate net::ERR_ABORTED signal's origin is not established. Repeated-failure
policy stopped speculative patches, deployment and chained E2E. On explicit
continuation, an isolated tree/selector fixture reproduced the failure in both
real normal and injected direct-recovery entry paths. RCC 1.0.19 excludes only
the exact hidden ellipsis sibling of data-search-result-target; literal text
and unknown shapes stay unchanged. Regression coverage includes collapsed and
expanded messages, Unicode/newlines/code, nested wrappers, ambiguous/wrong
turns and conversation identity. Promotion and a fresh single-manager gate are
still pending. Do not resend/release the quarantined attempt or rerun successful
earlier gates. CLI #106 and monitor follow-ups remain outside this correction.

Latest user clarification authorizes this correction through PR/CI/main and
exact-SHA deployment plus RCC reload. This supersedes the brief LIVE hold.
It does not authorize CLI updates, Chrome restart or historical UNKNOWN/claim
changes. Resume staged acceptance only on fresh, unclaimed targets after the
exact payload/build checks; stop another repeated failure for evidence review.

Aggregate RCC status versus direct state, presence freshness, and stale
GENERATING/probe fallback are separate follow-ups in GitHub #82, not proven
causes of this response-capture failure. Do not infer full-chain completion
from component acceptance.

왕복 절감 후속 구현은 `docs/exec-plans/completed/BCT_BOUNDED_VERIFICATION_20261014.md`에서
추적한다. verify, bounded CI wait, compact status와 durable result wait는 PR #81과
Windows 129개 테스트, main CI 및 LIVE/hosted connector E2E를 통과했다. 같은 7개 작업의
호스팅 호출을 2회로 줄인 연속 비교에서 7.692초 → 2.097초였다. 작은 표본이며 로컬 자체의
처리속도 향상이나 모델 추론시간 개선으로 해석하지 않는다. 사용 계약은 `docs/VERIFICATION.md`다.
별도 개선 원장 대신 기존 GitHub Issues를 사용하며 비차단 후속 병목은 #82에 기록했다.

`BCT_PLATFORM_PACKAGE_V1=LIVE_ACCEPTED`; `BCT_CORE_RELEASE_BOUNDARY=LIVE_ACCEPTED`.

- `D:\BCT\source`의 로컬 Git `main`이 유일한 공식 소스이며 GitHub
  `p4147691/BCT`의 `main`은 게시·백업·리뷰·CI 감사 원격이다. 현재 정합성은 문서에 금방 낡는 SHA를 복사하지 않고
  `origin/main`, 로컬 `HEAD`, `D:\BCT\runtime\current.json`의 `source_head`, `/health`의
  `release_sha`가 모두 같은지 기계적으로 비교해 판정한다.
- 운영 release는 `D:\BCT\runtime`, receipt와 session 상태는 `D:\BCT\data`에 있다.
- BCT core, MCP, health와 BCT Monitor가 한 서비스/한 release에서 실행된다.
- 파일·Git·GitHub·배포·서비스·RCC·Python/PowerShell/argv 실행과 지속 세션은
  BCT 구현과 공통 operation receipt를 사용한다.
- Python과 PowerShell은 일반 개발 실행으로 사용할 수 있다. 지속 mutation, 배포, 서비스 및
  브라우저 변경은 별도의 주의 경계를 유지한다.
- BCT runtime은 ACT 모듈을 import하지 않는다. 초기 `D:\PROJECTS\BCT` checkout과 연결
  worktree는 `D:\Archive\BCT-Bootstrap-20261013`에 rollback/bootstrap 증거로 보존했고,
  활성 BCT 소스 정본은 `D:\BCT\source` 하나뿐이다. ACT 외부 연동의 잔여 의존성은
  완전 전환 전까지 별도로 추적한다.
- 기능별 정확한 소유권은 `docs/CAPABILITY_OWNERSHIP.md`, 사용법은 `docs/USER_GUIDE.md`를 따른다.
- Core release에는 Core 실행 코드와 읽기 전용 status UI만 들어간다. Monitor, RCC, BDC의
  유지 소스는 `modules/`에 있지만 Core runtime에 복사되지 않는다.
- ChatGPT App은 기존 App ID와 연결을 유지한 채 `BCT Control` 1.0.0으로 이름·설명을
  변경했다. 원격 터널도 `BCT Control Private`로 정리했고, 로컬 인증 호출과 ChatGPT의 도구
  새로 고침에서 BCT MCP 22개 도구가 확인됐다.
- `bct_read`는 기존 파일 읽기를 유지하면서 `operation: "directory_tree"`로 제한된 폴더
  목록을 제공한다. 조회 결과는 file/directory/symlink를 구분하고 work root 밖 및 link/reparse
  point 추적을 막는다. 이 기능은 GitHub CI와 LIVE MCP의 실제 `D:\BCT` 조회로 검증했다.
- BCT RCC, BCT ChatGPT New Tab, BCT Auto Proxy는 각각 독립 설치 모듈로
  `D:\ChromeExtensions`에서 실행된다. Proxy helper/wireproxy의 실행 backend는
  `D:\BCT\runtime\modules\chrome-auto-proxy`이며 더 이상 ACT runtime을 사용하지 않는다.
- 구형 ACT MCP(18769)와 ADC agent(18766)는 exact PID·시작시각·명령줄 fence와 durable
  receipt로 퇴역했다. BCT Core(18790), RCC, Monitor Native Host와 Proxy는
  전환 후에도 정상이다.
- 과거 staging/verify 사본은 `docs/LOCAL_LAYOUT.md`에 기록한 SHA-manifested Archive로 이동했다.
  실행 중인 도구와 project 후보는 이동하지 않았다.

## 현재 결정

- 이름: BCT. 약어 풀네임은 미정. 저장소 p4147691/BCT, private, main.
- 기능을 원격으로 끌어다 쓰는 wrapper에 머물지 않고 실제 기능 소스와 테스트를 BCT에 둔다.
- 기존 ACT 운영과 MCP/Chrome 연결을 보존하면서 기능별로 전환한다.
- core / features / integrations의 작은 단일 패키지로 시작한다.
- node_id / 표시 속성 / connection generation / authenticated principal / work ownership을 분리한다.
- 공통 정책 판단 구현은 하나, 실행 직전 대상 검사와 원격 인증은 실행 경계에서 유지한다.
- 설계의 유일한 상세 기준은 docs/DESIGN.md다.

## 완료된 구현과 현재 경계

FIRST_SLICE_COMPLETE / GITHUB_INTEGRATION_V1_ACCEPTED / DEPLOYMENT_SERVICE_V1_ACCEPTED / MCP_V1_ACCEPTED / RCC_V1_ACCEPTED.
코어 구조·노드 신원·권한 경계 및 동시 변경/중복 실행/인계 계약을 구현했다.
파일 읽기·원자적 쓰기, Python test, expected HEAD·정확한 dirty set·new-file SHA proof 기반 Git commit을 BCT 소스로 구현했다.
13개 first-slice 로컬 테스트에서 실제 격리 Git 흐름, wrong principal, duplicate operation, UNKNOWN 중복 차단, foreign dirty, stale hash/HEAD, symlink escape 및 인계를 검증했다.
GitHub Actions run `38234844806`에서 최신 Actions major로 Windows CI가 통과했다.
ACT 전체 legacy feature 호환을 목표로 하지 않는다. BCT의 core, 개발 흐름, GitHub,
배포·서비스, MCP, bounded RCC 제어가 각각 live acceptance를 통과했다.
기존 RCC 탭/role binding은 계속 보존된다. 활성 GitHub Runner 네 개는 GitHub의 같은
runner ID·이름·label을 유지한 채 `D:\BCT\runtime\runners\github`로 이동했고 모두
`online / busy=false`가 확인됐다. 이동 receipt는 `D:\BCT\data\migrations`에 보존한다.

GitHub integration V1은 BCT 소스로 구현되었다. exact-SHA branch push, deterministic request marker를
사용한 PR 생성 중복 방지, required-check 조회, exact-head merge 및 verified `main` fast-forward를
공통 operation receipt와 resource claim으로 실행한다. 인증은 공식 `gh`의 기존 credential store를
사용하고 token은 BCT 상태에 저장하지 않는다. Git commit의 실행 전 확정 실패가 HEAD와 dirty set을
보존한 경우 claim을 안전하게 해제하는 회귀까지 포함해 전체 19개 로컬 테스트,
PR #2 Windows CI run `38241115179`, merge commit `9140bc07d7e0fac9b809a208818a20f6bf094653`,
merge-main push CI run `38241278661`이 통과했다. 동일 operation 및 새 operation ID의 중복
push/PR/merge가 실제로 추가 효과를 만들지 않는 것을 확인했다. 상세 계약은
`docs/GITHUB_INTEGRATION.md`, 증거는 `docs/exec-plans/completed/BCT_GITHUB_INTEGRATION.md`를 따른다.

실사용 중 발견한 commit-failure claim 문제는 PR #4, merge
`c770eb5595856776db63fbb085ea148f731bdb92`로 수정·CI 검증했다. 중앙 BOOTSTRAP의 BCT 상태도
PR #23, merge `f478d5e75c57e4e8455914b503d1c5f5fee41546`으로 갱신했다.

Deployment/service V1은 source checkout과 runtime을 분리한다. `bct_runtime_v1` named profile만
`D:\BCT\source`의 명시된 파일을 `D:\BCT\runtime\releases\<source-head>`로 옮길 수 있다.
clean main/exact commit, file SHA manifest, atomic current pointer, durable deployment receipt,
exact PID/executable/creation fingerprint/generation/instance health, duplicate operation fencing,
stop/restart 검증 및 failed-readiness 전체 rollback을 구현했다. focused 4개와 전체 23개 테스트,
compile 및 diff 검사를 통과했다. 상세 계약은 `docs/DEPLOYMENT_SERVICE.md`를 따른다.

PR #6의 exact head `a3e8cddcf3a1293741a14408a5ac9f5129e43147`은 Windows CI run
`38244408181` 통과 후 merge `5ac41fd61636a5c6a4486d84702ba22069c65c96`로 통합됐다.
해당 merge를 최초 운영 release로 배포해 manifest
`ae95acec3d830e19d6392e4676a03212c13e9bdeba744f969fb46854680d745a`와 모든 source/runtime
파일 해시 일치를 확인했다. service는 최초 PID 10672에서 정확히 한 번 restart되어 PID 19344,
generation 2가 되었고 health `OK`, duplicate deploy/restart 재호출에서 추가 process가 생기지 않았다.
ACT/MCP/RCC/Chrome은 이 acceptance에서 변경하지 않았다.

MCP V1은 별도 정책·receipt·service를 만들지 않고 BCT core service에 Streamable HTTP `/mcp`를
탑재한다. 실제 `OperationCoordinator.capabilities`에서 `bct_<capability>` 도구를 생성하므로
미구현 도구가 catalogue에 남을 수 없다. loopback endpoint는 별도 durable bearer token으로
인증되며 모든 실행은 기존 work owner, operation ID, resource claim 및 outcome 경로를 그대로
사용한다. focused test에서 무인증 401, initialize/list, exact 14-tool catalogue, work create/recover,
실제 read, duplicate receipt, conflicting work 거부를 검증했다. 상세는 `docs/MCP_INTEGRATION.md`다.

MCP source는 PR #8로 통합되었고, 실제 upgrade preflight에서 발견한 두 호환성 문제도 남기지
않았다. PR #9는 이전 release를 자기 manifest로 검증하면서 새 release는 새 profile과 exact match하게
했고 Windows restart 전 exclusive port release fence를 추가했다. PR #10은 health contract version을
도입해 V1 service는 V1 증거로 정확히 검사한 뒤 업그레이드할 수 있고, 새 V2 service는 MCP readiness를
반드시 증명하게 했다. 최종 live release는 `5d18519e9a0d3b68ef60ab7ee3c3551d741628ab`,
manifest `2f5b31d3340991429b162aff4c18ca3268b66d60b09a477d5ad06707f8486387`, PID 35428,
generation 4, health contract 2다. 표준 MCP protocol `2025-11-25`에서 무인증 401, 14개 exact tool,
실제 work/read/duplicate receipt를 확인했다. Codex global server `bct`를 stable endpoint에 등록하고,
새 Codex 프로세스가 BCT work 생성과 read를 실제 수행했다. 기존 ACT MCP 설정은 변경하지 않았다.

## 모델 전환

사용자는 Astra로 코어 구조·노드 신원·권한 경계 설계까지 마친 뒤 SOL로 구현을 이어가기를 선택했다.
이 문서는 SOL 인수인계 기준이다. 문서 작성이 앱 모델 설정 변경을 의미하지 않는다.
새 작업을 중복 생성하거나 초기 구조 토론을 반복하지 말고 첫 구현을 진행한다.

## 반복 금지

- ACT 데이터/운영 폴더 초기화, 기존 UNKNOWN operation 재실행 금지.
- ID/역할/프로필 이름만으로 기술 권한 부여 금지.
- 만료 lease만으로 살아 있는 실행을 takeover하지 않음.
- 동일 operation을 실패/timeout 후 자동 재실행하지 않음.
- source/설계 완료와 LIVE acceptance를 혼동하지 않음.
- 구현체를 BCT로 가져오기 전에 라이선스·의존성과 현재 계약을 확인.
- 기능 이전을 이유로 사용자의 기존 MCP/Chrome 설정을 임의 초기화하지 않음.

RCC V1은 현재 운영 확장 22개 파일과 Native Host source/manifest를 exact SHA 기준선으로 BCT에
보존했다. `relay_browser`는 exact instance만 사용하며 BCT operation ID를 Native Host와 확장의
mutation operation ID로 재사용한다. pre-dispatch 실패는 확정 실패로, dispatch 이후 응답 유실은
UNKNOWN으로 기록해 자동 재실행하지 않는다. state 응답의 token/secret/authorization은 BCT
receipt에 들어오기 전에 제거한다.

PR #13 head `72b50d391d5fd901696b732ac3d2779d1903112a`는 CI run `38254069968` 통과 후
merge `15f8ce551e7360ab77266c331758c0e249706d85`로 통합됐다. main CI run
`38254397056`도 통과했다. 전체 38개 테스트, compile, diff 검사가 통과했다. live release는
동일 SHA, manifest `35f4c8e2ccaa517e37b8449e888bce64f03003845abbf93e40dd6003f26288c6`,
PID 38252, generation 7이며 source/runtime mismatch는 0이다. MCP catalogue는 15개 도구를
노출하고 `bct_relay_browser` read-only state 호출과 duplicate receipt가 실제 RCC instance
`b91fe69d935f4e3893caa30836e4b13c`에서 통과했다. 기존 보호 탭 `594832035`와 다른 열린 탭,
bindings, pending 상태는 변경하지 않았다.

## 다음 작업

제어 경로와 브라우저 모듈의 ACT runtime 퇴역 및 활성 GitHub Runner 경로 이동은 완료됐다.
DesktopWindow Monitor 2.0은 Native HWND/thumbnail을 창의 정본으로 유지하고, 노드·조직
정보를 창 존재 판정에서 분리하며, 구형 ACT startup/focus 호출을 기본 비활성화했다. 기본 화면은
RCC가 실제 관측한 Chrome window/tab ID와 OPEN·active·generating 상태만 읽기 전용으로
보여준다. 이 `N1`, `N2` 표시는 순번일 뿐 역할·권한·소유권·물리 HWND를 만들지 않는다. PR #43,
merge `f00510b9c6411b4d6ee8dd5636594f4957f08cc6`과 main CI 통과 후 exact 6-file 설치 배포와
Chrome reload가 완료됐다. 같은 extension ID에서 새 Native Host 연결, BCT/Laya health와 RCC
보존까지 확인했다. 남은 순서는 SHA manifest를 남긴 구형 runner 백업/비활성 서비스 정리다. 이후 작업도 새 관리
계층을 추가하지 않고 같은 work/operation/receipt → GitHub main → exact deploy → live
acceptance 흐름으로 진행한다.

## Batch read 및 왕복 절감 완료

`bct_read`는 기존 file/directory-tree 계약을 유지하면서 최대 20개의 bounded read를 한
operation으로 처리한다. 모든 요청을 선검증하고 resource claim을 원자적으로 잡으며, 파일당
512 KiB·파일 합계 1 MiB·directory entry 합계 2,000 제한을 적용한다. receipt에는 content를
저장하지 않고 SHA와 메타데이터만 남긴다. 부분 실행 실패도 operation을 `FAILED`로 종결하고
claim을 해제한다.

PR #72는 CI 통과 후 merge `212623809a5cff60efa5543b90d531ed7512b90f`로 통합됐고 동일 SHA가
LIVE Core에 배포됐다. 전체 111개 테스트, compile, diff 검사가 통과했다. LIVE direct-MCP에서
5개 개별 read 165 ms 대비 한 batch 41 ms였고 모든 SHA가 일치했다. Hosted ChatGPT E2E의
`bct-batch-read-chatgpt-e2e-op-01` 영수증은 `FINISHED / APPLIED`, 5/5 OK, 27,751 bytes이며
ChatGPT가 관찰한 batch tool call은 4.930초였다. 서로 다른 경로의 수치는 직접 차감하지 않는다.

속도 우선 원칙은 같은 안전·승인 경계의 독립 read를 가능한 한 한 batch로 묶는 것이다. write,
배포, 서비스 제어, 브라우저 mutation의 승인 경계나 operation ID 멱등성, atomic claim,
UNKNOWN no-retry, exact-SHA 배포 조건은 완화하지 않는다.

## Tunnel health 및 MCP 지연 종결

### 2026-10-18 강제 재시작 후 복구 상태 — 외부 MCP ingress BLOCKED

강제 Windows 재시작 뒤의 read-only 점검에서 Core는 자동 복구됐다. `BCT Core
Supervisor`가 14:49 KST에 시작해 generation 104 / PID 16248로 `RUNNING`이며,
인증된 `/health`와 `/monitor/state`는 `200 OK`, MCP 22개 도구 ready를 반환한다.
AI-CODE-TEAM의 `ACT-GLOBAL-01`과 `ACT-WORKER-01` GitHub Runner도 online / idle이다.

하지만 tunnel supervisor에는 boot/logon trigger가 없고 터널 프로세스는 재기동되지
않았다. `runtimes status act-control`에는 재시작 전 PID 3424만 남아 있고, health
URL의 loopback probe (`127.0.0.1:50293`)는 connection refused다. 따라서 Core local
MCP (`127.0.0.1:18790/mcp`)는 정상이나 ChatGPT App의 private tunnel ingress는
현재 사용할 수 없다. 이 상태에서 기존 operation/claim을 재실행·해제하거나 터널을
중복 connect하지 않는다. 다음 작업은 exact tunnel supervisor의 안전한 boot/logon
복구 경로를 구현·검증한 뒤 단일 connect 및 health/MCP E2E로 확인하는 것이다.

Tunnel health metadata 복구는 PR #74로 완료됐다. merge
`3418bfa9b6eee46d488682bc34fad431e883a8a2`와 main CI가 통과했고 동일 SHA가 LIVE Core에
배포됐다. supervisor는 exact tunnel process가 살아 있을 때 중복 connect하지 않으며, 누락된
health URL 파일은 exact PID 소유의 유일한 live/ready loopback listener로만 복구한다. 현재 tunnel
PID와 시작시각은 유지됐고 `runtimes status`는 `healthy=true`, `ready=true`, `runtime_state=ready`,
`stale=false`다. 완료 증거는
`docs/exec-plans/completed/BCT_TUNNEL_HEALTH_RECONCILIATION_20261014.md`를 따른다.

Hosted ChatGPT의 단일 `bct_read` E2E는 1.816초였지만, 같은 exact request의 BCT tool handler는
15.517 ms, BCT ASGI 전체는 21.706 ms였다. tunnel poll 수신부터 local MCP 응답은 23.057 ms,
그 뒤 OpenAI control-plane response POST 완료까지 397.753 ms였다. 로컬 poll-to-post 합계는
420.810 ms이며 나머지 약 1.395초는 로컬 tunnel span 밖이어서 현재 설치된 tunnel-client
0.0.14로 더 분할할 수 없다. 공개 최신 v0.0.15에도 `resp_timing`/`trace_context`가 없으므로
미출시 master 기능을 위해 운영 binary를 교체하지 않는다. BCT Core 결함은 재현되지 않았고
추가 코드·LIVE 변경 대신 기존 bounded batch read를 같은 안전 경계의 read 왕복 절감 수단으로
유지한다. 상세 근거는 `docs/exec-plans/completed/BCT_MCP_TUNNEL_LATENCY_20261014.md`다.

후속 최신 확인: 공식 tunnel-client v0.0.16 release는 `resp_timing`과 opt-in trace context를
제공한다(공식 게시일 2026-10-06). 앞선 최신 릴리스 확인은 불완전했고 v0.0.15가 최신이라는
판단을 정정한다. 설치 버전 업그레이드 및 hosted 구간 재계측은 GitHub #82에서 추적하며,
기능 존재를 지연 해소로 간주하지 않는다.

## Deploy shutdown 및 UNKNOWN reconciliation 완료

터널의 지속 Streamable HTTP 연결이 열린 상태에서 Core shutdown listener는 닫혔지만 Uvicorn
process가 controller의 10초 검증 창 안에 종료되지 않는 운영 결함을 확인했다. 최초 배포
operation은 `DEPLOYMENT_ROLLBACK_UNVERIFIED` UNKNOWN으로 보존했고 재실행하거나 DB에서 claim을
직접 지우지 않았다.

PR #76은 Uvicorn graceful shutdown을 5초로 제한하고, 정확한 원본 UNKNOWN operation과 동일한
rollback receipt 파일·immutable release manifest·current pointer·running service release/manifest를
모두 확인하는 deploy reconciliation을 추가했다. reconciliation은 별도 resource에서 실행되고
검증 성공 시 store transaction 안에서만 원본 claim을 해제한다. Windows short/long path 차이는
문자열이 아니라 파일 identity로 비교한다.

PR #76의 request-drain timeout만으로는 FastMCP lifespan shutdown이 제한되지 않는다는 후속
LIVE 증거가 나왔다. 두 번째 배포도 UNKNOWN으로 보존했고 exact LIVE 복구 후 별도 reconciliation로
claim만 원자적으로 해제했다. PR #79는 authenticated shutdown에서 `should_exit`와 `force_exit`를
함께 설정해 5초 request drain 뒤 무기한 lifespan 대기를 건너뛴다.

로컬 focused 11개와 전체 116개 테스트, PR #79 Windows CI run `38494897550`, merge
`84a65e9dd0c85f0441e024f002f717ddccbcb0cb`, main CI run `38495142459`가 통과했다. 해당 release를
bootstrap한 뒤 persistent tunnel이 실제 `ready`인 상태에서 Core restart가 APPLIED였고 같은 tunnel
process가 다시 `healthy/ready`, runtime `ready`, non-stale 상태가 됐다. 후속 local MCP read도 예상
SHA로 통과했다. 상세 증거는
`docs/exec-plans/completed/BCT_DEPLOY_SHUTDOWN_RECONCILIATION_20261014.md`와
`docs/exec-plans/completed/BCT_DEPLOY_FORCE_EXIT_20261014.md`를 따른다.

## Generic desktop UI Automation 완료

BCT는 인증된 MCP에서 일반 Windows UIA 요소 조회와 `set_value`, `invoke`,
`toggle`, `select`, `expand`, `collapse`를 exact HWND 및 Window Lease에 묶어
제공한다. 원문 control name과 입력값은 durable evidence에 남기지 않으며,
텍스트는 OS locale과 무관한 UTF-8/ASCII-envelope 경계로 전달한다.

PR #231은 기본 UIA 경로를, PR #232는 사라진 exact target을 읽기 전용으로
증명한 뒤 기존 activation UNKNOWN은 보존하고 그 Claim만 해제하는
`desktop_window_activate_reconcile`을 추가했다. PR #232 merge
`ea7b9f84207ca1fed4f97a7f39b1e344cb13ea5d`는 PR/main CI를 통과했고 Core
generation 144에 READY/OK로 배포됐다. VTL Agent 2.3.2와의 authenticated LIVE
canary에서 10개 요소 조회와 다섯 semantic action의 실제 앱 postcondition,
Lease 해제, 기존 Chrome 9개 최상위 창 identity 보존을 확인했다. 상세 계약과
완료 증거는 `docs/exec-plans/completed/BCT_DESKTOP_UIA_CONTROL_20261019.md`를
따른다.

## Tunnel v0.0.16 및 UNKNOWN 계측 진행

터널 v0.0.16 cutover와 기존 Scheduled Task 기반 Supervisor 복원 검증은 완료됐다. Core LIVE는
`d28891146a0343606e716169b5e573f206825dc4` generation 147이며 exact v0.0.16 프로세스 하나와
Supervisor 하나가 READY다. Hosted read canary는 APPLIED였고 BCT 내부 단계를 밀리초 단위로
분리했다. 단, upstream `resp_timing`은 아직 운영자 영수증으로 되돌아오지 않아 hosted
queue/handback 잔여 구간은 숫자로 확정하지 않는다.

후속 실제 `bct_status(compact=true)` canary는 현재 LIVE
`b4663866417230d90347d2a295150d7a1a589b61`에서 ChatGPT turn, tunnel metric/debug event,
BCT `MCP_TIMING`을 같은 단일 성공 호출로 상관시켰다. 전체 13.570초 중 도구 호출 전 모델
구간 8.196초, control-plane enqueue부터 response acceptance까지 0.781초, 도구 결과 뒤 최종
답변까지 4.593초였다. 0.781초는 enqueue-to-poll 0.241초, local MCP HTTP 0.184205초,
dispatcher glue 약 0.004064초, response POST 0.351731초로 분리됐고 같은 호출의 BCT ASGI는
0.183009초였다. 따라서 이 샘플의 주 병목을 BCT Core나 터널 전체로 부르면 안 된다.
Monitor의 인접 snapshot에서는 0.161438초 중 RCC state가 0.147710초로 가장 컸으므로 compact
status 내부 최적화 후보는 RCC 조회다. 운영 프로세스는 재시작하지 않았고 임시 DEBUG는 INFO로
원복했으며 raw HTTP logging은 계속 꺼져 있다.

호출 전 구간을 반복 상관시키기 위한 최소 Core 계측은 PR #242로 병합되어 LIVE generation
154 / SHA `4b523ff597e5e8c1d528bb23d0d0e0fe2f6be7ab`에 적용됐다. 기존 RCC가 이미
보유한 `generationStartedAt`/`generationFinishedAt`과 비교할 수 있도록 privacy-safe
`MCP_TIMING`에 절대 밀리초와 인증된 POST `request_ingress`를 추가하고, status/capabilities
handler 종료도 같은 trace로 남긴다. `bct_status`는 그 호출의 server-generated opaque trace ID를
결과에 포함해 Hosted 결과와 로컬 단계를 시간 추정 없이 exact join한다. 요청 본문·헤더·토큰·사용자 텍스트와 caller trace는
기록하지 않는다. CI-equivalent local Core 628 tests, focused 7 tests, PR required CI가 PASS했고,
기존과 후보의 MCP catalogue는 43개/32,542 bytes/동일 SHA-256으로 확인됐다.

같은 ChatGPT 탭의 read-only status 3회에서 generation start→Core ingress 중앙값은 4.921초,
Core ingress→response complete는 0.185초, Core response→assistant complete는 3.390초였다.
동일 길이 no-tool control 3회의 assistant generation 중앙값은 3.753초였다. status 경로의 중앙
추가 시간 5.064초 중 Core는 0.185초뿐이므로, 과거 8.196초 pre-tool 지연을 Core 문제로 보지
않는다. 다만 나머지 Hosted 구간을 context/queue/reasoning/tool selection/argument/tunnel로 더
나누는 것은 consumer ChatGPT에서 `UNOBSERVABLE`이다. 43개 catalogue는 32,542 bytes이고,
Desktop 19개가 16,189 bytes를 차지하며 37개 capability wrapper는 설명/title을 제외하면 같은
입력 schema 구조다. 다음 최소 실험은 기존 full endpoint를 보존한 별도 minimal endpoint의
randomized A/B이며, 실측 전에는 tool 수를 원인으로 확정하거나 기존 endpoint를 교체하지 않는다.
상세는 `docs/exec-plans/completed/BCT_ISSUE82_PASSIVE_BOUNDARY_20261020.md`를 따른다.

현재 후속 작업은 새 operation마다 `CLAIM_RESERVED`, `DISPATCH_INTENT`, effect result/uncertain,
receipt intent/persisted를 작은 redacted SQLite journal로 남기고 `bct_operation_get` 및 Claim
diagnostics에서 읽게 하는 것이다. 과거 읽기 전용 UNKNOWN 9건에는 별도
`claim_reconcile` 경로를 사용한다. `read`, `system_inspect`, `github_pr_status`만 허용하며 원래
UNKNOWN receipt는 바꾸지 않고 exact Claim만 원자적으로 해제한다. mutating capability는 이
경로에서 거부한다. 그 다음 순서는 execute → relay_browser → orchestrate이며, 외부 postcondition
증거 없이 mutation을 재실행하거나 Claim을 해제하지 않는다.

## RCC 대화 이름 변경 UI 계약 보완

2026-10-21 LIVE에서 exact N2 대화의 이름 변경이 `RENAME_ACTION_NOT_FOUND / NOT_APPLIED`로
종결됐다. Core 경로·Claim·exact UUID 문제는 아니었다. ChatGPT 사이드바가 접히면 기존
content 구현이 `/c/<uuid>` anchor를 찾지 못했고, 현재 메뉴의 한국어 표기가 `이름 바꾸기`에서
`이름 변경`으로 달라진 실제 DOM 계약을 회귀가 다루지 못했다.

수정 계약은 현재 URL의 conversation key가 exact target과 일치할 때
`app-shell-header-context-menu-surface`의 단일 대화 메뉴를 우선 사용하고, 기존 sidebar row 메뉴는
호환 fallback으로 남긴다. `이름 변경` 표기를 명시적으로 인식하며, 접힌 sidebar와 현재 한국어
메뉴를 재현한 content 회귀를 포함한다. broad selector나 임의의 다른 대화 메뉴로 우회하지 않는다.

첫 LIVE 재검증에서 메뉴 동작은 복구됐지만 현재 ChatGPT 대화상자의 제목 필드는 명시적
`type="text"`가 없는 기본 text `<input aria-label="채팅 제목">`라서 기존 editor selector가
`RENAME_INPUT_NOT_FOUND / NOT_APPLIED`로 안전 종료했다. selector는 dialog 안의
`input:not([type])`을 포함하도록 보완했고, composer와 숨은 file input 배제 및 단일 dialog editor
조건은 그대로 유지한다. 실제 UI 계약을 재현한 회귀로 이 경로를 고정한다.

exact code SHA `598d2952298a11343829b899103c6ad1507ef204`는 GitHub Actions run
`39545497251` 전체를 통과했다. 설치 payload의 `conversation_rename.js`만 exact hash
`946b47eaa133e2d47b7b6867978466b8f5b771bae76946bd3c889f0d06e0d4a4`로 교체하고 same-ID
RCC를 reload했다. N2 exact UUID `6ad4bb5d-6624-83ee-b045-e57fdad5120e`에서 임시 제목으로
변경한 operation과 원래 제목으로 복원한 operation이 모두 `APPLIED`였으며 실제 ChatGPT 탭
제목도 양방향 일치했다.

배포 중 공식 Monitor reload operation은 별도 `create-chat-window` operation이 이미
`FINISHED / UNKNOWN`인데도 남긴 전역 `rcc-instance:<id>` Claim 때문에
`RESOURCE_ALREADY_CLAIMED:FOREIGN_WORK`로 효과 시작 전 차단됐다. 원본 UNKNOWN 및 Claim은
변경하지 않았고, 현재 RCC가 응답하며 실행 중인 호출이 없음을 대조한 뒤 이미 승인된 same-ID
host reload만 분리 실행했다. 후속 Claim 정책 작업에서는 종료된 UNKNOWN 기록과 실제 실행 잠금을
분리하고, create-window의 전역 Claim이 무관한 reload/rename을 영구 차단하지 않도록 다뤄야 한다.

## Conversation Network A 유연성 결정

2026-10-21 사용자 결정으로 대화망의 `Manager`는 실행 권한이나 필수 단일 자리가 아니라 자유로운
안내 태그로 확정됐다. 첫 노드 자동 Manager, Manager 정확히 한 명, 후임 없는 이동 거부,
Manager 부재 시 기능 보류를 구현하지 않는다. 600 ms 정지 길게 누르기는 태그를 빠르게 붙이는
UI 편의 기능일 뿐이며 이동을 감지하면 취소한다.

프로젝트와 대화망은 사용자 화면에서 하나의 `대화망 / 작업 범위`로 통일한다. 기존
`conversation_network_projects.project_id`는 호환 저장 식별자로 재사용하고 별도 network registry를
추가하지 않는다. 대화 UUID는 현재 범위 하나만 갖고 이전 membership은 복구 이력용 EXCLUDED로
보존한다. N번호는 표시 별칭으로 계속 영구·비재사용한다. 우클릭은 실제 ChatGPT 제목 변경,
범위, 역할, 식별 정보를 한 창에서 다루며 기존 쓰레기통 복구 UI에 이전 범위·역할을 함께 보존한다.
구현·검증 현황은 `docs/exec-plans/active/BCT_CONVERSATION_NETWORK_FLEXIBLE_A_20261021.md`를 따른다.

## Monitor BCT 전환 후 legacy 조직 조회 경계

2026-10-20 읽기 전용 점검에서 `check_monitor_live_organization.py`가 찾는 ACT
`/organization/*` endpoint는 응답하지 않았다. 이는 BCT Core/RCC 장애가 아니라, 2026-10-13
`729d403` 전환에서 ACT 조직 authority를 퇴역시키고 Monitor 기본 화면을 BCT의 RCC 관측
window/tab projection으로 바꾼 결과다. 같은 시점의 LIVE BCT `/monitor/state`는 RCC instance와
열린 ChatGPT 대화를 정상 관측했다.

따라서 legacy `D1-3` 같은 조직 노드 표기는 BCT-native snapshot의 입력이 아니며, 이를 얻기 위해
퇴역 ACT를 재가동하거나 legacy endpoint를 복구하면 안 된다. 대화망에 표시할 후속 표기는 BCT가
관측한 exact conversation key를 기준으로 별도 read-only display mapping으로 정의해야 한다. 이는
relay routing/권한을 만들지 않는다.

## RCC 재구축 V2 통합 계획

RCC V1의 API별 Browser Adapter 연속 분리는 Stage 7F에서 중단했다. 2026-10-20 source
HEAD `40083383a236072d7e14cea4530eb1719adc327e` 기준 background 5,103줄과 content
4,458줄에는 정책이 이미 차단한 ACT/등록/rename/일반 mutation 구현이 활성 Simple Relay 및
read-only diagnostics와 함께 남아 있다. 다음 작업은 Adapter를 하나 더 만드는 것이 아니라
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_INTEGRATED_20261020.md` 순서대로 진행했다.

먼저 source-only로 차단된 레거시와 zero-caller 경로를 일괄 제거하고, storage/browser/native/
observation 플랫폼 경계와 Simple Relay/content 활성 도메인을 큰 단위로 분리한다. 전체 CI와
exact payload/rollback 검증이 끝난 뒤에만 별도 명시 허용을 받아 coherent payload를 same-ID
확장에 한 번 배포·reload한다. 그전까지 LIVE 설치본, Chrome, Native Host, binding은 변경하지
않는다. 기존 tab move/create/close/reload 및 window create Adapter는 optional source로 보존하되
active loader나 Relay 권한에 연결하지 않는다.

## RCC 재구축 V2-1 source 완료

정책상 차단된 background/content 레거시와 그 전용 zero-caller helper를 call graph와 계약
테스트로 확인해 일괄 제거했다. background는 5,103→2,080줄, content는 4,458→1,780줄이며
파일 내부 참조가 선언뿐인 named function은 0개다. 폐기 구현을 직접 호출하던 테스트 16개도
활성 계약 테스트와 중복되지 않음을 확인하고 제거했으며, 남은 RCC JavaScript 테스트 20개가
모두 통과한다.

Simple Relay V0, exact conversation/read-only diagnostics, fail-closed 오류 계약은 유지했다.
optional browser mutation Adapter는 source에 남아 있지만 loader와 manifest에서 제외했다.
LIVE 설치본, Chrome, Native Host, Relay binding은 변경하지 않았다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_STAGE1_LEGACY_PRUNE_20261020.md`를 따른다.
다음 구조 단계는 V2-2 플랫폼 경계 일괄 분리이며 계속 source-only다.

V2-1 exact commit `46f1772ecddb2079198101692b40eb5155f87b1e`는 GitHub Actions run
`39388085496` 전체를 통과했다. 별도로 `c2e7d39` 이후 main의 LIVE 미반영분을 감사한 결과,
runtime profile에 포함되는 배포 후보는 opt-in compact/hybrid MCP catalogue 코드였고 나머지는
RCC source-only와 문서였다. durable deploy operation `bct-live-deploy-20261020-46f1772`가 해당
exact commit을 BCT Core generation 165로 APPLIED했다. Core health는 READY/OK, production MCP
catalogue는 full 44-tool 기본값을 유지한다. RCC 설치본·Chrome·Native Host·Relay binding은
변경하지 않았고 설치 RCC/Native Host 해시와 관측 instance/session/tab/conversation identity가
배포 전후 동일하다.

## RCC 재구축 V2-2 source 완료

활성 background의 storage, exact tab ID 조회와 receiver 주입, Native Messaging, tab 관측
listener, runtime lifecycle을 책임 단위 다섯 플랫폼 모듈로 한 번에 분리했다. `background.js`의
직접 `chrome.*` 호출은 24곳에서 0곳, 크기는 2,080줄에서 1,969줄로 줄었다. storage key,
native command/content message 이름, Simple Relay 원문/receipt, read-only diagnostics와 기존
fail-closed 오류는 유지했다.

기존 read Adapter와 tab/window mutation Adapter는 source에 보존하되 active loader에서
제외했다. 남은 RCC JavaScript 테스트 21개와 focused Python 계약 18개가 통과했다. LIVE RCC
설치본, Chrome, Native Host, Relay binding은 변경하지 않았다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_STAGE2_PLATFORM_BOUNDARIES_20261020.md`를 따른다.
exact source commit `a2d20c80d9d3b35b134f6f0f86220fb947a0b202`의 GitHub Actions
`BCT CI` run `39390634666`도 전체 통과했다. 다음 단계는 V2-3 활성 도메인·content 일괄
분리이며 계속 source-only다.

## RCC 재구축 V2-3 source 완료

endpoint, Simple Relay, receipt, read-only diagnostics와 runtime route를 background domain/boot
파일로 분리하고, content의 DOM 판별, submit/read executor, 단일 router, activity reporter를
분리했다. `background.js`와 `content.js`는 각각 3줄 조립 진입점이며 domain의 직접 `chrome.*`
호출과 active bundle의 zero-caller named function/top-level 상태는 모두 0개다.

기존 native command 15개, runtime/content message 8개, storage key, 원문·UUID·receipt와
fail-closed 오류 계약은 유지했다. JavaScript 테스트 23개, focused Python 계약 18개와 전체
BCT Python 회귀 842개가 통과했고 실제 loader/manifest 순서로 background와 content bundle을
실행하는 시험도 통과했다.
LIVE RCC 설치본, Chrome, Native Host, Relay binding은 변경하지 않았다. 상세는
`docs/exec-plans/completed/BCT_RCC_REBUILD_V2_STAGE3_DOMAIN_CONTENT_20261020.md`를 따른다.
exact source commit `62317038bd50b848f6d49714029630c3fda03040`의 GitHub Actions
`BCT CI` run `39393918353`도 전체 통과했다. 다음 단계는 V2-4 통합 Release Candidate
검증이며 계속 비-LIVE다.

## Monitor 섬네일 실제 Chrome 창 번호 결합 후속

2026-10-21 LIVE `v2.0.12`에서 BWM 노드 카드는 `N4/N7/N9`를 표시했지만 데스크톱 섬네일 속
실제 Chrome 창에는 `N4/7/9` 오버레이가 나타나지 않았다. RCC의 동일 Chrome
`window_id 594834491`과 Native Host의 대상 `HWND 132482` 및 D2 좌표는 모두 정상이라 정보
부재가 아니었다. Native thumbnail geometry와 RCC/Chrome geometry가 비동기로 도착하는데,
Native 좌표 저장 후 display-only 결합을 재계산하지 않는 순서 결함이 원인이다.

수정은 fresh Native HWND geometry 저장 직후 미대조 lineage에 한해서만 Chrome geometry를
갱신하고 표시 전용 `window_id → HWND` projection을 다시 계산한다. 같은 projection generation,
desktop, geometry는 한 번만 시도하므로 과거 Monitor 부하 문제를 되살리는 polling이 아니다.
exact action binding, RCC, Native Host, Claim 및 기존 UNKNOWN은 변경하지 않는다. focused overlay,
HWND, minimized, interaction, backpressure, deployment 회귀와 Monitor 구조 검사를 통과한 뒤
정확한 main SHA와 설치 payload를 배포하고 reload 후 실제 화면 수락을 받아야 한다.

후속 대조에서 위치 라벨 D2가 정상인 사실로 `window_id → HWND` 결합 성공을 다시 확인했다. 남은
결함은 기존 인라인 썸네일 렌더러가 per-image 장식 중 전체 렌더러를 재진입하고 자식 배지에 창
좌표를 중복 적용하던 구조였다. 활성 경로를 독립 `monitor-bct-thumbnail-projection.js`로 옮기고
구 인라인 구현을 제거했다. 새 계약은 N4/N7/N9 동일 창 투영, 캡처 DOM 교체 후 유지, 열린 창은
썸네일 내부·최소화 창은 하단 요약만 사용함을 검사한다. LIVE reload 뒤 shared runtime의
`thumbnail_projection`에서 `matched=1`, `rendered=1`과 실제 화면 `N4/7/9`를 함께 확인해야 한다.

## Monitor 비활성 데스크톱 회색 캡처 후속

2026-10-21 BWM `2.0.23`에서 D2 썸네일이 단색 회색으로 바뀐 원인은 레이어나 노드 투영이 아니라
Windows DWM 캡처 의미였다. 다른 가상 데스크톱의 정상 창은 Native 관측에서 `cloaked=2`이며,
WGC가 이 HWND에 대해 오류가 아닌 단색 회색 프레임을 반환해 마지막 정상 캡처를 덮었다.

Monitor는 이제 `cloaked=0` 창만 픽셀을 새로 캡처하고, 비활성 데스크톱 창에는 마지막 정상
blob/data 캡처를 유지한다. 기존 정상 캡처가 없을 때만 안전한 정보 placeholder를 사용한다.
HWND 식별, 노드 번호, 선택 테두리, 최소화 표시는 변경하지 않는다. 새 계약 검사와 Monitor
관련 JavaScript 검사, Python Monitor/대화망 33개 회귀가 통과했다. 레거시
`check_monitor_ncodex_rdp_route.js`는 이미 제거된 N-CODEX 문자열을 요구해 기존과 동일하게
실패하며 이번 변경의 기능 실패가 아니다.

표시 전용이고 복구 가능한 BWM 변경은 로컬 정본의 정확한 커밋과 로컬 게이트 뒤 백업을 만든 후,
LIVE E2E와 같은 커밋의 GitHub CI를 병행할 수 있다. Core/RCC/Native Host, 프로토콜, DB/Claim,
Chrome 변경, 메시지 전송은 계속 exact-head CI 성공 뒤 LIVE로 진행한다.

## RCC 신규 대화 단일 작업 경계

2026-10-21 `브라우저 브릿지` 대화망을 실제 UI와 RCC inventory로 대조했다. N2/N3의 기존 대화
Simple Relay는 각각 두 차례 왕복과 정확한 표시가 확인됐다. N13에서 처음 생성됐던 blank tab
`594834964`는 후속 read-only runtime에서 conversation
`6ad88177-eaf0-83ee-81af-81b5e7512892`의 완료 대화로 전환된 사실이 확인됐다. 따라서 이를 빈 탭
후보로 재사용하지 않는다. 미완료 범위는 새 operation으로 만든 탭의 첫 메시지부터
응답·UUID·호출자 반환까지다.

RC4는 BCT의 `create-and-send`를 RCC의 단일 `new-chat-send` 명령으로 연결한다. 호출자는 exact
Chrome `window_id`, 원문, timeout만 제공한다. RCC가 기존 tabs.create Adapter, 반환 tab ID,
첫 메시지 1회, conversation UUID, 응답 전문과 hash receipt를 한 operation ID로 관리한다. 같은
operation ID 재호출은 저장된 결과만 반환하고 새 탭/메시지를 만들지 않는다. 신규 대화에서는
send button이 검증되지 않으면 Enter fallback을 금지하고, RCC 내부 deadline을 외부 pipe보다
2초 먼저 끝내 transport UNKNOWN 경합을 피한다. 기존 저수준 create/send 명령은 계속 차단한다.

이 경로는 실제 Chrome 탭과 메시지를 만들므로 로컬 회귀와 RC 검증 → exact main CI 성공 →
설치본 백업·same-ID reload → 일반 ChatGPT의 BCT Control 호출 LIVE E2E 순서를 유지한다.
당시 LIVE RCC 48파일은 RC3 inventory와 missing/extra/mismatch 0으로 일치했으며, RC4 manifest의
rollback baseline도 당시 48파일 aggregate
`9ef3eb39080f68589c5e856147905bb47706171a1c9673362a988122a80d0e46`였다. 이후 Project Run binding
후보를 LIVE에 적용하면서 설치 payload가 49파일로 바뀌었으므로 아래 Project Run 릴레이 배포 전에
rollback baseline을 다시 현재 설치본과 대조해야 한다. 과거 39파일 pre-rebuild 기준으로 복구하지
않는다.

일반 ChatGPT의 첫 `create-and-send` E2E는 도구 선택에는 성공했지만 효과 시작 전에 종료된 과거
`create-chat-window` UNKNOWN의 전역 `rcc-instance:<id>` Claim에 차단됐다. 해당 정확한 operation을
RCC에서 읽었을 때 result와 pending이 모두 없고 동일 instance/current session은 OPEN이었다. 따라서
원본 UNKNOWN을 성공·미적용으로 바꾸거나 재전송하지 않고, 새 `create-and-send`가 시작되기 직전에만
동일 RCC의 무실행 상태를 다시 입증하고 Store 트랜잭션에서 정확한 구 Claim 하나를 실행 잠금에서
퇴역시키는 bounded 보완을 진행한다. pending/result/신원 불일치/다른 오류/실행자 존재 시에는 기존
차단을 유지한다. 이 보완은 로컬 회귀와 exact-head CI 성공 뒤 Core에 배포하고, 일반 ChatGPT에서
새 탭 1개·최초 메시지 1회·UUID·응답·Manager 반환을 실제 확인해야 완료다.

## RCC 신규 대화 실제 효과와 영수증 재조회 결함

2026-10-21 exact operation `rcc-new-chat-live-e2e-9c1675e-20261021-02`는 요청한
Chrome window `594834519`에 tab `594835024`를 한 번 만들고 원문을 한 번만 제출했다. 실제
ChatGPT UI와 RCC inventory에서 UUID `6ad8a8c2-3d74-83e8-9e08-96152cf39efb`, user turn 1,
assistant turn 1, 정확한 응답 `RCC_NEW_CHAT_E2E_OK_20261021_2049`를 확인했다. 이 효과는
재전송하지 않는다.

BCT가 이를 UNKNOWN으로 남긴 직접 원인은 새 영수증 저장소 `newChatReceiptsV1`를 기존 읽기
전용 `result` 명령이 조회하지 않은 경로 단절이다. 후속 후보는 기존 `result` 명령에서 이 저장소의
terminal receipt를 읽고, `RCC_NEW_CHAT_*` UNKNOWN만 exact operation·instance·session·tab·window·
conversation·text hash·reply·result hash로 검증해 원본 UNKNOWN을 보존한 채 exact Claim만 정산한다.
Browser Bridge나 새 통신 계층은 추가하지 않으며 같은 메시지를 다시 보내지 않는다. 현재 로컬 focused
회귀와 RC inventory는 PASS이고, exact-head CI·Core/RCC 정확 SHA 배포·same-ID reload·기존 operation의
result-only LIVE 정산이 남았다.

## RCC 신규 대화 LIVE 수락 및 지연 판정

exact main `4760a19366b828e67e68360794044887ab561629`의 CI run `39616902897`은
SUCCESS이고, exact 49-file RCC payload를 백업 후 설치해 same-ID reload했다. RCC instance와 열린
탭은 보존됐다. 기존 operation `rcc-new-chat-live-e2e-9c1675e-20261021-02`의 늦은 응답은 원문을
재전송하지 않고 UUID `6ad8a8c2-3d74-83e8-9e08-96152cf39efb`와 exact reply/hash로 회수했으며,
원본 UNKNOWN은 보존하고 exact Claim만 `no_resend=true` 영수증으로 해제했다.

일반 ChatGPT의 공개 BCT Control 도구에서도 exact window `594834491` 대상으로 동일 고수준
`create-and-send`를 실행했다. tab `594835040`, UUID
`6ad8cfc0-30fc-83ee-adaf-73fa0267df55`, user/assistant 각 1 turn, exact reply와 result hash를
확인했고 중복 탭·중복 메시지는 없다. 탭 생성과 UUID 확보는 약 7초였지만 ChatGPT 생성 자체가
`597904 ms` 걸렸다. 따라서 2분 이상 지연의 주원인은 Chrome API/RCC가 아니라 원격 응답 생성이다.
진행 중 `pending=true`가 새 대화의 state/tab/window/UUID를 숨기는 관측성 결함은 별도 최소 후보로
보완하되, 전송 의미·timeout·Browser Bridge·재시도 정책은 바꾸지 않는다.

## 2026-10-22 RCC 신규 대화 진행 상태 관측 LIVE 수락

exact main `12b8c442a07c9ecf4e210a74929a62aefd3dd243`의 BCT CI run
`39622162603`은 scope, preflight, Core 4개 shard와 Browser Bridge를 모두 통과했다. 49-file
payload aggregate `bb90671339456fa9a30d52732fe108746ae36799ba9e7fd46b271cf1e4f2157b`를
백업 후 설치하고 same-ID reload했다. RCC instance
`6174664e1c1b4e6db1d4729c841db3c9`와 기존 탭 9개는 유지됐고 session만
`bba404ee8f0e4a40bc09b94a28d9d769`로 갱신됐다.

기존 ordinary-ChatGPT E2E operation은 reload 후에도 exact tab `594835040`, UUID,
text SHA, reply와 result hash로 읽혔고 `replayed=true`였다. 새 탭·메시지 전송은 없었다.
이번 변경은 실제 pending 동안 state/tab/window/UUID/stage timing을 비민감 상태로 보여주는
관측성만 추가한다. terminal 결과에서는 `pendingStatus=null`을 유지한다.

BWM의 단색 회색 plate는 capture 실패가 아니라 current desktop 카드의 solid gray CSS였다.
exact main `c846b27e3e7432fba2d5d0062aa3e8749801e39e`와 CI run `39610757767`을
LIVE 적용한 뒤 fresh capture에서 D1/D2 실제 이미지와 전체 UI를 확인했다. 남은 별도 현상은
extension reload 직후 공식 Alt+M 초기화 전 blank shell이 잠시 남을 수 있는 초기화 race다.

## 2026-10-22 Project Run 첫 LIVE 바인딩 회귀

Project Run foundation exact HEAD `23be3a4b2f25978782d7b0997a344d1e4314087a`는 CI run
`39661769198` SUCCESS 후 로컬 정본 main
`23235e23e1e9c6facbba9b49d3f1d7d6762cf372`, Core generation 177로 적용됐다.
Browser Bridge scope의 plan과 orchestration session은 생성됐지만 첫 node-sync
`browser-bridge-project-run-node-sync-20261022-01`은
`UNKNOWN / ORCHESTRATION_BINDING_UNVERIFIED`로 끝났다.

원인은 RCC 모듈 분리 과정에서 `conversation-bind`를 정책상 레거시 차단 목록에 남기고 실제
native handler도 제거했지만 Core의 durable node-sync 계약은 계속 해당 명령을 사용한 불일치다.
후속 후보는 current instance/session/tab/conversation과 deterministic receipt를 모두 검증하는
정확한 binding handler만 복구한다. 레거시 메시지 전송·bootstrap 경로는 되살리지 않는다.
또한 첫 bind의 명시적 `NOT_APPLIED`를 UNKNOWN으로 만들지 않고, 이미 남은 UNKNOWN은 원본
request digest와 RCC 등록 영수증 부재를 읽기 전용으로 입증할 때만 exact Claim을 정산한다.
부분 적용이나 영수증 존재 시에는 계속 차단한다. 현재 active RCC JavaScript 전부와 RC inventory,
orchestration/Project Run 63개 회귀가 통과했으며 exact-head CI와 RCC same-ID reload 및 LIVE
recovery/node-sync/Manager checkpoint가 남았다.

## 2026-10-22 Project Run 오케스트레이션 릴레이 후속

exact feature `8f0077bd49d1d2825f57743f65d484cc6ceb1b6d`의 CI run `39669486198`이
전체 통과한 뒤 로컬 main `250e89345e5e073a80beedf39339ce1599fbf1d3`, Core generation 178과
49-file RCC payload에 적용했다. RCC instance와 기존 탭은 보존됐다. 첫 UNKNOWN node-sync는
RCC 영수증 부재와 미적용을 확인해 원본 UNKNOWN을 보존한 채 exact Claim만 정산했고, 새
node-sync operation으로 N13 Manager 및 N14/N3/N2 Worker의 exact UUID·tab·window·binding을
확보했다. Project Run은 Manager epoch 1과 exact attachment로 READY가 됐다.

첫 Manager checkpoint delivery `orch.send.74c08cbc7f95b24dff6fd06372b03094`는 사용자 메시지를
보내기 전에 `RCC_NATIVE_COMMAND_LEGACY_MUTATION_DISABLED:send`로 `NOT_APPLIED` 종료됐다.
`conversation-bind`와 마찬가지로 RCC 재구축 때 Core가 계속 쓰는 durable `send` 계약까지 제거한
구조 불일치가 원인이다. 이 delivery는 재전송하지 않는다.

후속 후보는 generic legacy mutation을 복구하지 않고 `send`만 `ORCHESTRATION`으로 분류한다.
exact instance/session/tab/conversation/binding receipt/attachment generation을 전송 직전과 결과
저장 때 다시 확인하고, intent를 먼저 영속화한다. 같은 delivery ID의 pending·terminal receipt가
있으면 다시 제출하지 않으며, 확장 reload 뒤 예전 session 결과도 저장하지 않는다. 새 content
executor는 exact user turn 1회 제출과 assistant 전문 회수만 담당하고 기존 RCC result polling
형식으로 영수증을 남긴다. RCC 1.0.27 candidate는 51파일 aggregate
`ff672173ffbf087833da6fe744f2135c9aa8a866666dfcfa20530b61c4105a5f`이며, JavaScript 전체 회귀,
Project Run/RCC source baseline 19개와 release inventory 검증을 통과했다. exact-head CI, 로컬 main
병합, same-ID reload, 새 attachment 재동기화와 새 Manager checkpoint LIVE 왕복은 아직 남았다.

배포 직전 감사에서 RC manifest의 rollback baseline이 위의 과거 48파일 상태를 계속 가리키는 결함을
발견해 RCC 설치와 reload를 중단했다. 현재 설치본은 승인된 Project Run binding 후보의 정확한 49파일
payload이며 aggregate는
`dcf27a7b32797d0bbc10405dee2ee9c743d638000ad4ae0673c11f791400ef2d`다. manifest를 이 49파일
목록으로 교정한 뒤 release verifier로 현재 설치본의 missing/extra/mismatch 0과 rollback aggregate를
다시 확인했다. 이 manifest 교정도 exact-head CI와 로컬 main 병합을 거쳐야 하며, 그 전에는 RCC를
변경하거나 reload하지 않는다.

## 2026-10-22 RCC delivery ledger 구조 재설정

Project Run/RCC의 후속 국소 수정을 동결하고, 새 격리 작업본
`D:\BCT\worktrees\rcc-delivery-ledger-v1-20261022`에서 호출 경로와 저장소를
READ-only로 다시 대조했다. 현재는 Simple Relay와 durable orchestration이 같은 ChatGPT
메시지 효과를 서로 다른 명령·binding·receipt·Claim 구조로 표현한다. LIVE DB에는
오케스트레이션 전용 테이블 20여 개, 세션 20개 중 ACTIVE 11개, Assignment 28개 중
UNKNOWN 7개가 남아 있다. 반면 Simple Relay는 exact 대화 UUID와 기존 DOM adapter로 실제
왕복을 수행한 이력이 있다.

새 기준은 한 Manager UUID, 한 Worker UUID, 한 `delivery_id`이다. 상태는
`NOT_SENT -> SENT_WAITING -> REPLY_CAPTURED -> RETURNED`만 정상 진행으로 인정하고,
사전 거부는 `NOT_APPLIED`, 확인된 Worker 실패는 `FAILED`, 효과 경계가 불명확하면
`NEEDS_REVIEW`로 종료한다. RCC 세션·tab/window·attachment generation은 재접속용 관측값이며
영구 권한이나 전역 차단 조건이 아니다. 상태기계와 실제 명령·storage·SQLite inventory의
정적 계약 9개가 PASS했다.

상세 계획은
`docs/exec-plans/active/BCT_RCC_DELIVERY_LEDGER_V1_20261022.md`에 있다. 격리 HEAD
`a24c0350e429111b16c1a1ce2f398e71076fa19f`에는 기존 exact-turn DOM adapter만 재사용하는
`delivery-start -> delivery-status -> delivery-return` 소스 경로가 구현됐다. 세 호출은 같은
`delivery_id`와 exact Manager/Worker UUID를 사용하고 BCT의 `relay_deliveries` 한 행과 RCC의
`deliveryLedgerMirrorV1` 한 mirror로만 진행한다. 진행 중 mirror는 terminal retention limit로
제거되지 않으며 전체 RCC/desktop Claim을 사용하지 않는다.

Python 상태·ledger·feature·기존 RCC transport 회귀 28개 PASS, 기존 orchestration 포함 85개
PASS, RCC extension JavaScript 전체 suite PASS다. 이후 source 후보를
`RCC_REBUILD_V2_RC5`, extension `1.0.28 · Delivery Ledger V1`로 패키징했다. 격리 HEAD는
`1cd3eb1b063786c2ebd8c6e5ee3c2596c2c847fd`, candidate inventory는 52파일 aggregate
`10b85114421b7e5ce33da8cc00c027f8b278d7bddf87308de59aac60f326f998`, 보존된 rollback
baseline은 49파일 aggregate
`dcf27a7b32797d0bbc10405dee2ee9c743d638000ad4ae0673c11f791400ef2d`다. 패키지·상태기계·
transport focused Python 45개, RCC extension JavaScript 전체 suite, RC inventory verifier와
`git diff --check`가 PASS했다.

PR #271은 로컬 정본 main에 병합되고 remote main까지 fast-forward되어 exact main
`9f35125516cf2f841aeed75ab53a9a5a02cc5a48`이 됐다. main CI run `39699667585`의 scope,
preflight, Browser Bridge와 Core 4개 shard가 모두 성공했다. RC5 52파일 aggregate
`10b85114421b7e5ce33da8cc00c027f8b278d7bddf87308de59aac60f326f998`를 설치했으며,
직전 51파일 설치본 aggregate
`ff672173ffbf087833da6fe744f2135c9aa8a866666dfcfa20530b61c4105a5f`는 exact backup과
보존 디렉터리에 남겼다.

same-ID reload 뒤 RCC instance `6174664e1c1b4e6db1d4729c841db3c9`와 exact N13 Manager
`6ad7f5b6-c834-83e8-9c00-ff70bab4204d` / N14 Worker
`6ad7ff62-fa64-83ee-a485-1138f1538e53`로 두 번 연속 LIVE 왕복했다.
`dlv-live-20261022-a`와 `dlv-live-20261022-b`는 각각
`SENT_WAITING -> REPLY_CAPTURED -> RETURNED`를 통과했고, 응답 전문 22자의 SHA-256은
각각 `3e45566c6e014bc02618e1eb58eabdf28e418c6ae5e536a6594388131d771923`와
`b128c4f68cfb53c3a1b443f430c05b3201b13bd2430633eeaf97104f8f4bc389`로 기대 문자열과
일치했다. 중간 recovery reload로 RCC session은 `9799625ceafc4dcaa2285b5a073d96fc`로
바뀌었지만 첫 delivery는 `RETURNED/replayed=true`였고, 같은 delivery-start 재호출도 새 전송
없이 기존 terminal row만 반환했다.

따라서 Phase 6 얇은 왕복은 `LIVE_ACCEPTED`다. 다음 단계는 이 단일 ledger 위에 Wake-up,
역할 전환, 다중 Worker를 하나씩 추가하는 Phase 7이다. 기존 orchestration/Simple Relay
legacy 삭제는 Phase 7 수락과 caller-zero 증명 전까지 금지한다.
