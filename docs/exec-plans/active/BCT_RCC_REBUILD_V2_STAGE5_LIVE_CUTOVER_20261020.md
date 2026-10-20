# RCC Rebuild V2-5 — 단일 LIVE 전환

상태: `RC1_ACCEPTANCE_FAILED / EXACT_ROLLBACK_COMPLETE / RC2_PENDING_CI`

## RC1 전환과 안전 복구

- 구현 기준: `62049dc4810e03c86f9b1b92b3c184d303df488e`, CI run `39398670419` PASS
- RC1 aggregate: `ce3a33bb107dc74eb23da50d0d48a85dab656c69ee65e90caca763cde55f1606`
- 전환 전 LIVE 39파일 aggregate:
  `93b1cfdc4e6602ddfb7de46b6fa00eb10173db01f911c1530c952cc1439e583b`
- verified backup:
  `D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-20261020-181950`
- 실패 후보 보존:
  `D:\ChromeExtensions\RCC\rcc-v2-failed-stage5-20261020-181950`

RC1 46파일을 exact 검증한 뒤 설치 경로 전체를 한 번에 바꾸고 `reload-extension`을 정확히
한 번 호출했다. 새 Native session이 생성됐고 네 열린 ChatGPT tab 모두 `probe-tabs` OK였다.
extension ID, Native Host executable SHA, profile, storage와 Simple Relay binding은 바꾸지 않았다.

## 수락시험 실패 증거

- 방향: Manager `6ad5afa4-b1e0-83ee-8692-aec4bb51523e` → Worker
  `6ad4bb5d-6624-83ee-b045-e57fdad5120e`
- operation ID: `rcc-v2-5-m2w-20261020-01`
- 원문 길이/SHA-256: `63` /
  `e001cc21343663b2029e2eb5c570fef2f93493adfed09b06de500177044eb970`
- receipt: `NOT_APPLIED / RELAY_EXACT_USER_TURN_NOT_CONFIRMED`
- 충돌 증거: Worker에 새 generation start/finish가 관측되고 assistant lifecycle도 완료됨

영수증과 실제 효과 정황이 충돌했으므로 재전송과 Worker→Manager 반환을 하지 않았다. RC1
설치 폴더를 실패 증거로 보존하고 직전 39파일 폴더를 원자적으로 되돌린 뒤 rollback reload
1회를 수행했다. 복구 뒤 핵심 설치 SHA와 Native Host SHA, binding, Core shadow match가 모두
전환 전 기준과 일치한다. 시험 원문은 중복 위험 때문에 다시 보내지 않는다.

## 원인과 RC2

1. 제출 확인이 `user` DOM node 개수 증가에 의존했다. ChatGPT가 오래된 turn을 가상화하면 새
   turn이 생겨도 총 node 수가 늘지 않아 false negative가 된다.
2. content는 이 경우 `UNKNOWN`을 반환하지만 background가 `submitted:false`를
   `NOT_APPLIED` 증거로 잘못 축소했다.
3. 클릭 뒤 exact turn 확인 전에 relay execution record를 저장하지 않아 사후 반환 경로도
   닫혔다.

RC2는 before turn key 집합에 없던 exact 새 user turn의 고유 key로 제출을 확인한다. UI
activation 직후 recovery record를 먼저 저장하고, background는 명시적 `effectState=NOT_APPLIED`
만 재시도 가능한 미적용으로 분류한다. 그 외 post-activation 불확실성은 `UNKNOWN`이다.

- RC2 aggregate: `e7b0bd98b74fd982031565c3701fe68f0c7b45e2984deba8c490867272756c39`
- exact 46-file rehearsal:
  `D:\BCT\runtime\rehearsals\rcc-rebuild-v2-rc2-e7b0bd98`
- RCC Node tests: 24 PASS
- focused Python release/source tests: 17 PASS
- verifier: source + staged RC2 + restored LIVE baseline PASS
- 전체 로컬 suite: service integration 13개가 isolated runtime
  `SERVICE_READINESS_TIMEOUT`으로 실패. RCC test 실패는 없으며 원격 CI를 최종 gate로 둔다.

## 다음 gate

RC2 exact source commit의 GitHub Actions 전체 통과를 확인한 뒤에만 현재 LIVE baseline을 다시
backup하고 RC2를 단일 전환한다. 새 수락 원문은 첫 시도와 구분되는 새 operation ID를 사용하되,
RC1 원문을 재사용하지 않는다. 두 방향 `SUBMITTED` 영수증과 postcondition이 모두 일치해야
V2-5를 완료로 바꾼다.
