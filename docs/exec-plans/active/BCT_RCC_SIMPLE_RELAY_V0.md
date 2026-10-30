> **현재 운영 규칙 — 2026-10-30 우선 적용:** [측정 증거·작업 지속 정책](../../MEASUREMENT_EVIDENCE_AND_PROGRESS_POLICY.md) 및 루트 `AGENTS.md`가 이 실행계획의 과거 UNKNOWN/Claim/HOLD 설명보다 우선한다. 측정 결과의 정확성 증거가 없으면 `MEASUREMENT_UNVERIFIED`로 무효 처리하고 그 결과만으로 Claim·작업 중단·재시도 금지를 만들지 않는다. 원인 측정기를 고치면서 다른 진단·개발을 계속한다. 일반 메시지 중복은 수신 노드가 판단하며, 실제 고위험 외부 변경만 정확한 대상과 사용자 승인으로 보호한다. 아래 과거 실행·영수증·시험 서술은 역사로 보존하며 현행 권한 부여 규칙이 아니다.

# RCC Simple Relay V0

상태: `LIVE_RETURN_ACCEPTED`

## 목적

고정된 Manager와 Worker ChatGPT 대화 사이에서 원문을 한 번 전달하는 작은 경로를
제공한다. 이 경로는 기존 RCC의 orchestration, role registry, 자동 응답 회수, ACK 진단,
대화 생성 및 재전송과 독립적이다.

## 계약

- `simple-relay-bind`: Manager·Worker의 exact conversation UUID 두 개만 저장한다. tab/window
  번호는 저장하거나 호출자에게 요구하지 않는다.
- `simple-relay-send`: `from=manager|worker`, 원문, operation ID만 받는다. 대상 탭은 UUID로
  매번 다시 찾는다.
- 수신 대화가 생성 중이거나 초안이 있거나 UUID가 달라지면 제출 전에 실패한다.
- 제출 뒤의 불명확한 결과는 `UNKNOWN` receipt로 남기며 자동 재시도하지 않는다.
- receipt에는 방향, 대상 UUID, 원문 길이·SHA-256 및 제출 상태만 남긴다. 원문·응답 전문,
  노드, 작업표, 자동 판단은 저장·생성하지 않는다.
- `simple-relay-return`: 앞선 Manager→Worker 제출 receipt를 명시하면, 그 제출 전의 assistant
  turn 수보다 하나 이상 늘어난 IDLE Worker 응답 하나만 읽어 원문 그대로 Manager에 전송한다.
  이전 응답, 생성 중 응답, 빈 응답, 12,000자 초과 응답은 Manager에 전송하지 않는다.

## 제외 범위

기존 RCC 경로와 그 historical state는 삭제하거나 변환하지 않는다. V0는 별도 storage key와
명령을 사용하므로 롤백은 extension payload를 직전 백업으로 되돌리고 reload하는 한 단계다.

## 검증 순서

1. Node pure-contract 및 JavaScript syntax 검사.
2. Python RCC feature의 입력·resource·receipt 계약 검사.
3. exact live payload backup 및 atomic replacement. 완료: backup은
   `D:\BCT\runtime\backups\rcc-extension-20261020-090800`.
4. extension reload 후 read-only `state`에서 build
   `2026-10-20-simple-relay-v0`와 두 UUID를 확인. 완료.
5. Manager→Worker 원문 한 건을 전송하고 `SUBMITTED` receipt만 확인한다. 완료:
   Worker의 user/assistant turn count가 각각 하나 증가한 뒤 IDLE로 돌아왔다.

이 acceptance는 기존 대화에 시험 원문 한 건을 제출한 실제 UI 효과를 포함한다. 반환 경로는
extension 1.0.23에서 LIVE 검증됐다. 새 Manager→Worker 시험은 Worker가 IDLE이 되고 assistant
turn 수가 정확히 하나 증가한 뒤에만 읽혔고, 33자 원문이 Manager에 `SUBMITTED`로 한 번
전달됐다. 이전 1.0.22 send receipt에는 pre-send assistant turn 수가 없으므로 반환을 거부했다.
이는 기존 응답을 추측해 전송하지 않는 fail-closed 동작이다.

Core adapter도 같은 source head `7df4f06a5e9390175392e341e567b02631fa6ce5`로 배포됐고,
`bct-core` generation 160의 health `OK`를 확인했다.

## 2026-10-21 신규 대화 후속과 유지보수 경계

`create-and-send` 신규 대화의 실제 탭·원문·응답 효과는 한 번 확인됐지만 BCT는 새 영수증
저장소와 원본 operation ID를 조회하지 못해 UNKNOWN으로 기록했다. 같은 메시지는 재전송하지
않고, 새 영수증 projection과 exact original-ID readback을 추가했다.

이 UNKNOWN의 전역 `rcc-instance:<id>` Claim이 이후 공식 reload까지 막던 문제는 reload를
별도 maintenance Claim으로 분리해 해결한다. maintenance는 실행자 없는 FINISHED effect 기록과는
공존하지만 RUNNING RCC-wide effect와는 Store 트랜잭션에서 양방향 충돌한다. 또한 reload 직전
exact RCC state에서 생성 중 endpoint가 하나라도 있으면 실행하지 않는다. 원 UNKNOWN·receipt·
Claim은 영수증 검증 전까지 변경하지 않으며, reload 후 persisted result를 읽어 검증된 경우에만
reconcile이 정확한 원 Claim을 정산한다.
