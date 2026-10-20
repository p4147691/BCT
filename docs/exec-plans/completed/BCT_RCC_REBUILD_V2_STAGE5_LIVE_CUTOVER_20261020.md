# RCC Rebuild V2-5 — 단일 LIVE 전환

상태: `RC1_EXACT_ROLLBACK_COMPLETE / RC2_LIVE_ACCEPTED / V2_5_COMPLETE`

## RC1 전환과 안전 복구

- 구현 기준: `62049dc4810e03c86f9b1b92b3c184d303df488e`, CI run `39398670419` PASS
- RC1 aggregate: `ce3a33bb107dc74eb23da50d0d48a85dab656c69ee65e90caca763cde55f1606`
- 전환 전 LIVE 39파일 aggregate:
  `93b1cfdc4e6602ddfb7de46b6fa00eb10173db01f911c1530c952cc1439e583b`
- 당시 verified backup:
  `D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-20261020-181950` (V2-6에서 최신 RC2 backup과
  중복임을 검증한 뒤 정리)
- 당시 실패 후보:
  `D:\ChromeExtensions\RCC\rcc-v2-failed-stage5-20261020-181950` (V2-6에서 RC1 manifest와
  exact 일치를 검증한 뒤 정리)

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

RC2 exact source commit의 GitHub Actions 전체 통과를 확인한 뒤 현재 LIVE baseline을 다시
backup하고 RC2를 단일 전환한다. 새 수락 원문은 첫 시도와 구분되는 새 operation ID를 사용하되,
RC1 원문을 재사용하지 않는다. 두 방향 `SUBMITTED` 영수증과 postcondition이 모두 일치해야
V2-5를 완료로 바꾼다.

## RC2 최종 LIVE 수락 결과

- exact source/main: `447c6bb5296e8a8bb7f9896d65ed49e48a385afb`
- GitHub Actions: run `39402641746`, preflight/Core 4 shard/Browser Bridge 전체 PASS
- LIVE payload: 46파일, aggregate
  `e7b0bd98b74fd982031565c3701fe68f0c7b45e2984deba8c490867272756c39`
- RC2 backup:
  `D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-rc2-20261020-184845`
- 당시 immediate rollback:
  `D:\ChromeExtensions\RCC\rcc-v2-pre-rc2-stage5-20261020-184845` (V2-6에서 아래 RC2 backup과
  39파일 SHA가 동일함을 확인한 뒤 중복본 정리)
- reload: `rcc-v2-5-rc2-reload-20261020-01`, exactly one successful same-ID reload
- post-reload: 새 Native session, binding 불변, 여섯 열린 tab의 `probe-tabs` 전부 OK
- Manager→Worker: `rcc-v2-5-rc2-m2w-20261020-01`, `SUBMITTED`, 원문 60자,
  SHA-256 `09375f061252b2965ceb5e89f28d0e252b14cb6b76db2f29f974b2f12f2c5aaf`
- Worker→Manager: `rcc-v2-5-rc2-w2m-20261020-01`, `SUBMITTED`, 응답 10자,
  SHA-256 `5365e0b45f4a830703aa1a16bc1c9dedd3ec5ea7403d50f878612d3e44bd56f5`
- 최종 postcondition: Manager/Worker 모두 generation 완료·IDLE, 각 message count 6/6,
  Core shadow `matches:true`
- Native Host executable SHA-256:
  `78087b6a1ece5793be22028c6c002f44eb2fb81f74609d8bf9893b8dae7a1d30`

이 결과로 V2-5는 완료다. V2-6은 LIVE payload를 변경하지 않고 과거 후보·중복 backup만
정리했으며, 복구에 필요한 최신 RC2 backup은 위 경로에 유지했다. 최종 종료 증거는
`BCT_RCC_REBUILD_V2_STAGE6_CLOSEOUT_20261020.md`에 있다.
