# RCC Simple Relay V0

상태: `IMPLEMENTED_LOCAL_VALIDATION_PENDING_LIVE_RELOAD`

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
- Worker 응답을 Manager에 보내는 것은 별도의 명시적 `from=worker` 단일 전송이다. V0는
  응답을 읽거나 요약하거나 자동 전달하지 않는다.

## 제외 범위

기존 RCC 경로와 그 historical state는 삭제하거나 변환하지 않는다. V0는 별도 storage key와
명령을 사용하므로 롤백은 extension payload를 직전 백업으로 되돌리고 reload하는 한 단계다.

## 검증 순서

1. Node pure-contract 및 JavaScript syntax 검사.
2. Python RCC feature의 입력·resource·receipt 계약 검사.
3. exact live payload backup 및 atomic replacement.
4. 사용자 수행 extension reload 후 read-only `state`에서 새 build ID와 두 UUID를 확인.
5. 사용자 승인 시 Manager→Worker 원문 한 건만 전송하고 `SUBMITTED` receipt만 확인한다.
