# RCC Simple Relay V0

상태: `RETURN_IMPLEMENTED_LOCAL_VALIDATION_PENDING_LIVE_RELOAD`

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
local test를 통과했으며 다음 exact payload reload 뒤 이 단일 시험 receipt만 대상으로 LIVE
검증한다.
