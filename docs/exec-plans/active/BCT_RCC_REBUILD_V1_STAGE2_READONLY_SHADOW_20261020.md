# RCC Rebuild V1 — 2단계 Read-Only Shadow

상태: STAGE_2_COMPLETED_LIVE_READ_ONLY_SHADOW

## 허용된 LIVE 효과

사용자 승인 범위는 canonical installed extension payload에 후보 파일을 배치하고, 같은
extension ID의 확장을 한 번 재로드하는 것까지다. Native Host, Chrome 대화 탭, Relay binding,
extension storage, composer와 실제 메시지 전송은 변경하지 않는다.

## 후보 구조

`core/shadow.js`는 기존 `state` 명령이 이미 읽는 chat tab, endpoint, Simple Relay V0 binding을
순수 Core `identity`/`state` 함수로 다시 판정한다. 결과는 `state.coreShadow`에만 붙는다.

- `mode: READ_ONLY_SHADOW`
- Manager/Worker별 Core 상태와 기존 관측 상태의 일치 여부
- 이미 activity telemetry에 있는 user/assistant/turn count만 복사한 message count
- browser API, DOM, storage, Native pipe, Relay send 호출 없음

loader는 Core 파일을 background에서만 먼저 읽는다. manifest의 content script 목록은 바꾸지
않으므로 기존 열린 탭의 content receiver·DOM protocol은 그대로다.

## LIVE gate

1. exact source commit의 CI 성공
2. 기존 LIVE payload·Native Host·binding·두 endpoint를 재확인
3. LIVE payload의 timestamped exact backup 생성
4. `core/` 후보를 먼저 복사하고 hash를 확인
5. loader/background/content/manifest를 exact source bytes로 배치
6. same-ID extension reload를 정확히 한 번 수행
7. Native `state`에서 새 build와 `coreShadow`를 읽고 두 conversation의 UUID·상태·count가 일치하는지 반복 확인

어느 gate라도 실패하면 이전 exact payload를 복원하고 같은 ID로 재로드한 뒤 read-only state만
확인한다. 메시지는 보내지 않으며 UNKNOWN 효과를 재시도하지 않는다.

## 완료 증거

- source commit `a977a6f`의 GitHub Actions `BCT CI` run `39353500261`: 전체 PASS
- exact backup: `D:\BCT\runtime\backups\rcc-rebuild-v1-stage2-exact-20261020-103204`
  (32 files, source LIVE와 SHA-256 불일치 0)
- 후보 5개와 active 파일 4개를 installed extension에 배치한 뒤 source/LIVE hash 불일치 0
- same-ID extension reload 요청은 정확히 한 번 성공했다.
- post-reload manifest `1.0.24`, background build
  `2026-10-20-rcc-core-shadow-v1`, `coreShadow.mode=READ_ONLY_SHADOW`
- Manager와 Worker는 각각 `CONNECTED`, `6:6:6` count이며 binding UUID는 유지됐다.
  1초 간격 3회 state read에서 동일 결과를 확인했고 두 열린 content receiver도 read-only probe에
  응답했다.

Native Host, Chrome 탭 새로고침/이동, Relay binding/storage, composer와 메시지 전송은 하지
않았다. 다음 3단계는 content protocol 호환성 전환이며 별도 승인 없이는 시작하지 않는다.
