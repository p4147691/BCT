# RCC Rebuild V1 — 6단계 Legacy 변경 경로 차단

## 목적

새 Simple Relay와 읽기 전용 조회만 남기고, 기존 orchestration/ACT/노드·창 관리 경로가
메시지·탭·binding·저장 상태를 바꾸지 못하게 한다.

## Source 정책

`legacy/command_policy.js`가 Native command와 Content runtime message를 각각 분류한다.

- 허용: `simple-relay-bind`, `simple-relay-send`, `simple-relay-return`, 상태·진단·과거
  영수증의 읽기 전용 조회, 확장 lifecycle maintenance (`reload-extension`).
- 차단: create/move/close tab/window, register/bind/promote/ensure, legacy send/wakeback,
  queue recovery, result ACK, worker reload, conversation rename, ACT·autoDirective·workerResult
  등의 기존 자동 mutation 경로.
- 미등록 command/message도 fail-closed로 거부한다.

## 검증

`test_legacy_command_policy_v6.js`는 새 Relay/read-only 허용, legacy mutation 차단과
background guard의 선행 순서를 검사한다. 기존 capture recovery test도 Legacy recovery가
chat tab/DOM recovery를 호출하지 않고 차단되는지 검사하도록 전환했다.

## LIVE gate

source test와 remote CI가 통과한 뒤 설치본에 policy, loader, background만 배치하고 same-ID
extension reload 한 번으로 활성화한다. 이후 state/probe read-only 확인과 허용 command 1개,
차단 command 1개의 무효화 확인을 한다. 차단 command는 실제 효과가 없는 `register`로만
검증한다.

## LIVE 완료

remote CI `39357982486` 통과 뒤 exact extension backup(38 files, path/hash mismatch 0)을 만든
후 policy, loader, background를 source hash와 일치하게 배치했다. same-ID extension reload는 한
번만 수행했다. post-reload Manager·Worker는 모두 `CONNECTED`, existing binding은 유지됐다.

`register` command를 존재하지 않는 role/conversation 값으로 한 번 호출한 결과는
`ok=false`, `effectState=NOT_APPLIED`,
`RCC_NATIVE_COMMAND_LEGACY_MUTATION_DISABLED:register`였다. 호출 전후 두 대화의 state/count와
binding은 변하지 않았다. 탭 새로고침·이동·새 노드 생성·메시지 전송은 없었다.
