# RCC Rebuild V2-4 — 비-LIVE Release Candidate

상태: `SOURCE_RC_ASSEMBLED / LOCAL_PASS / CI_PENDING / RCC_LIVE_UNCHANGED`

## 범위

V2-1~3의 source payload를 하나의 Release Candidate로 고정하고 다음을 자동 검증한다.

- active background/content loader graph
- `boot → domain → platform`, `content_router → content modules` 의존 규칙
- native/runtime/content/popup 허용·차단 message matrix
- extension ID, Native Host, storage key, wire message 호환성
- exact candidate payload와 현재 LIVE rollback payload의 파일별 SHA-256
- V2-5용 backup/rollback 절차

설치본, Chrome, Native Host와 Simple Relay binding은 변경하지 않는다.

## Chrome Extensions API 점검 반영

공식 Chrome 문서 기준으로 Tabs API와 Native Messaging은 Content Script가 직접 쓰는 경계가
아니다. Content Script는 Service Worker에 메시지를 보내고, Service Worker는 덜 신뢰되는
Content Script 발신자와 payload를 검증해야 한다. `storage.local`은 확장 제거 전까지 유지되는
로컬 durable 영역이고 `storage.session`은 확장 reload/update와 브라우저 재시작 때 지워지는
휘발성 영역이다. unpacked extension reload는 `runtime.onInstalled`의 update로 취급된다.

현재 V2 구조의 Service Worker/Platform 경계는 이 원칙과 맞았다. 추가로 다음 누락을 보완했다.

1. runtime 메시지는 같은 extension ID인지 먼저 확인한다.
2. `relay:activity`와 `relay:getPendingStatus`는 top-frame ChatGPT Content Script만 허용한다.
3. `relay:getState`는 같은 extension page만 허용한다.
4. Content Router는 다른 extension ID 발신자를 거부한다.
5. 활성 호출자가 없는 `webRequest` permission을 제거했다.
6. 차단된 legacy 메시지를 보내던 popup을 `relay:getState` 전용 read-only UI로 바꿨다.

참조한 공식 문서:

- https://developer.chrome.com/docs/extensions/reference/api/runtime
- https://developer.chrome.com/docs/extensions/reference/api/tabs
- https://developer.chrome.com/docs/extensions/reference/api/storage
- https://developer.chrome.com/docs/extensions/develop/concepts/native-messaging
- https://developer.chrome.com/docs/extensions/develop/concepts/messaging

## 후보와 rollback 기준선

- 후보 이름: `RCC_REBUILD_V2_RC1`
- exact candidate files: 46
- candidate aggregate SHA-256: `ce3a33bb107dc74eb23da50d0d48a85dab656c69ee65e90caca763cde55f1606`
- 비-LIVE 조립 경로:
  `D:\BCT\runtime\rehearsals\rcc-rebuild-v2-rc1-ce3a33bb`
- current LIVE rollback files: 39
- rollback aggregate SHA-256: `93b1cfdc4e6602ddfb7de46b6fa00eb10173db01f911c1530c952cc1439e583b`

`modules/rcc/release/rcc_v2_rc.json`은 후보와 rollback의 모든 파일 경로·크기·SHA-256,
active graph, optional/excluded 목록과 호환 계약을 기록한다. 후보 source에는 개발 test와
retired ACT 파일이 남아 있어도 배포 payload에는 포함되지 않는다. V2-5에서는 후보 46개만 든
exact staging 전체를 한 번에 전환해야 하며 기존 폴더에 부분 복사하지 않는다.

optional Browser payload 11개는 후보에 보존하지만 active loader에는 없다. ACT bridge 4개와
구 compatibility `simple_relay_v0.js`는 후보에서 제외한다.

## backup/rollback 계약

`modules/rcc/release/ROLLBACK.md`에 exact precondition, 전체 backup, staging 검증, 단일 same-ID
reload, mismatch/UNKNOWN 시 재전송 금지와 전체 rollback 순서를 고정했다. Native Host, Chrome
profile, storage와 binding은 후보 배치 및 rollback 대상이 아니다.

현재 LIVE 폴더는 `--live-root` 읽기 전용 검증에서 39개 파일 전체가 rollback inventory와
일치했다. 후보 rehearsal 폴더는 46개 파일 exact 검증에서 extra/missing 0개였다.

## 로컬 검증

- RCC Node 계약 테스트: 23개 PASS
- `tests/test_rcc_source_baseline.py`: 14개 PASS
- `tests/test_rcc_release_candidate.py`: 3개 PASS
- candidate + LIVE rollback exact verifier: PASS
- 전체 BCT Python suite: 845개 PASS
- Python compileall: PASS
- `git diff --check`: PASS

remote CI 결과는 구현 commit 뒤 이 문서에 exact SHA/run으로 추가한다.

## LIVE 변경 금지선

- `D:\ChromeExtensions\RCC\extension` 파일 변경 없음
- Chrome extension reload/탭 동작 없음
- Native Host executable/manifest/registry 변경 없음
- Simple Relay binding/storage 변경 없음
- 실제 Manager↔Worker 메시지 전송 없음

다음 V2-5는 이 V2-4 exact main SHA의 CI 통과와 별도 사용자 허용 뒤에만 시작한다.
