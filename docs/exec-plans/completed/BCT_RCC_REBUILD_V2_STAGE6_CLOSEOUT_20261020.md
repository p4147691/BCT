# RCC Rebuild V2-6 — 정리와 종료

상태: `COMPLETE / LIVE_UNCHANGED / RC2_RECOVERY_RETAINED / EXECUTION_DOCS_CLOSED`

## 1. LIVE 호출 그래프 판정

- LIVE 경로: `D:\ChromeExtensions\RCC\extension`
- payload: 46파일, 207,728 bytes
- aggregate SHA-256:
  `e7b0bd98b74fd982031565c3701fe68f0c7b45e2984deba8c490867272756c39`
- active loader graph: background 25파일, content 6파일, 중복 `relay_core.js`을 제외한 30개
  loader 대상과 진입점/manifest/popup 등 release 계약 파일
- optional Browser payload: 11파일
- excluded legacy payload: 5파일 모두 LIVE에서 부재

`rcc_v2_rc.json` exact manifest와 verifier로 LIVE와 RC2 rehearsal을 다시 대조했다. LIVE 46파일은
manifest와 일치한다. 호출자 0인 optional Browser 11파일은 통합 계획에서 “보존하되 활성화하지
않을 기능”으로 확정한 Adapter/receipt 계약이므로 구파일 삭제 대상으로 분류하지 않았다.
제외 legacy 5개는 이미 없어서 LIVE에서 삭제한 파일은 0개다.

## 2. 최종 구조와 계약

```text
extension/
├─ boot/       background 조립·route 등록
├─ core/       identity·state·conversation·transport·shadow
├─ domain/     endpoint·Simple Relay·receipt·read-only diagnostics
├─ platform/   storage·exact tab·Native Messaging·관측·lifecycle
├─ content/    router·DOM·submit/read·activity
├─ legacy/     기존 오류 계약의 fail-closed policy
├─ browser/    비활성 optional Adapter와 receipt contract 11개
├─ background_loader.js / background.js
├─ content_loader.js / content.js
└─ manifest.json / popup.html / popup.js / relay_core.js
```

- exact manifest: `modules/rcc/release/rcc_v2_rc.json`
- verifier: `modules/rcc/release/verify_release_candidate.py`
- rollback 절차: `modules/rcc/release/ROLLBACK.md`
- Simple Relay 원문·UUID·storage key·wire message·기존 오류 계약: 변경 없음

## 3. 정리한 후보와 backup

삭제 전 exact 경로, 디렉터리 여부, reparse point 부재와 보호 경로 불일치를 확인했다.

- `D:\ChromeExtensions\RCC\extension.backup-*` 10개: 버전 1.0.8~1.0.20 과거 설치 backup
- `D:\ChromeExtensions\RCC\.pr202-1.0.21-staged`: 빈 이전 staged 디렉터리
- `D:\BCT\runtime\rehearsals\rcc-rebuild-v2-rc1-ce3a33bb`
- `D:\ChromeExtensions\RCC\rcc-v2-failed-stage5-20261020-181950`
- `D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-20261020-181950`
- `D:\ChromeExtensions\RCC\rcc-v2-pre-rc2-stage5-20261020-184845`

RC1 rehearsal과 failed candidate는 RC1 manifest 46파일과 exact hash 일치했다. 두 pre-RC2
39파일 backup은 aggregate
`93b1cfdc4e6602ddfb7de46b6fa00eb10173db01f911c1530c952cc1439e583b`와 exact 일치하므로 최신
RC2 복구본 한 개만 유지했다. 정리 합계는 15개 디렉터리, 452파일, 5,587,932 bytes다.

## 4. 보존한 복구·수락 증거

- 최신 RC2 복구본:
  `D:\BCT\runtime\backups\rcc-rebuild-v2-stage5-rc2-20261020-184845`
- exact RC2 rehearsal:
  `D:\BCT\runtime\rehearsals\rcc-rebuild-v2-rc2-e7b0bd98`
- Manager→Worker receipt: `rcc-v2-5-rc2-m2w-20261020-01`, `SUBMITTED`, 원문 60자,
  SHA-256 `09375f061252b2965ceb5e89f28d0e252b14cb6b76db2f29f974b2f12f2c5aaf`
- Worker→Manager receipt: `rcc-v2-5-rc2-w2m-20261020-01`, `SUBMITTED`, 응답 10자,
  SHA-256 `5365e0b45f4a830703aa1a16bc1c9dedd3ec5ea7403d50f878612d3e44bd56f5`
- Native Host executable SHA-256:
  `78087b6a1ece5793be22028c6c002f44eb2fb81f74609d8bf9893b8dae7a1d30`

## 5. 영향과 종료 판정

V2-6에서는 LIVE extension 파일, Chrome, Native Host, extension ID, profile, storage, binding과
대화에 쓰지 않았다. reload나 relay 전송도 수행하지 않았다. exact RC2와 복구본을 보존했고,
과거 후보·중복 backup만 제거했다. V1/V2 실행 문서는 `docs/exec-plans/completed/`로 이동한다.

종료 전 로컬 검증:

- RCC JavaScript 계약 테스트 24개: PASS
- release candidate Python 테스트 3개: PASS
- RCC source baseline Python 테스트 14개: PASS
- module layout Python 테스트 9개: PASS
- LIVE RC2 / rehearsal RC2 / retained rollback exact verifier: PASS
- Python compileall, `git diff --check`: PASS

종료 기록 commit `aef81006a3c611da75b8af96397ecc6702010ba6`은 main에 반영됐고 BCT CI
run `39404680776`의 scope와 docs-only gate가 PASS했다. 이로써 RCC Rebuild V2는 종료다.
