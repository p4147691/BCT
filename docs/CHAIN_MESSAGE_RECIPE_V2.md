# Chain Message Recipe V2

## 이 문서의 범위

이 문서는 **이 체크아웃의 소스 동작**을 설명한다. 테스트 통과는 main 병합·설치·
LIVE 검증의 증거가 아니다. 실행 중인 버전은 Core 상태와 정확한 영수증으로 별도 확인한다.

대표 입구는 `bct_chain_message`다. 일반 작업 요청은 이 입구를 사용한다.
사용자가 Task Message 또는 Send Message를 명시한 경우에만 그 방식을 직접 쓴다.
`bct_task_message`는 사용자 방향을 다듬는 Set Direction의 다른 이름이 아니다.

## 실제 호출 흐름

```text
사용자의 요청 또는 정확한 BA/CA 반환
  ↓
bct_chain_message(instruction=요청) 또는 action="prepare"
  └─ bct_set_direction(action="prepare") 내부 호출
      ├─ 현재 Core/런타임/Work/작업 영수증/CI Inbox 조회
      ├─ bct_check_conversation_network 내부 호출
      │    열린 Node Info + RCC + 저장된 대화망 이력
      └─ A가 판단할 내부 질문과 사용 가능한 대표 명령 목록 반환
  ↓ 실제 A의 판단 턴 — BCT가 AI 대신 생각하지 않음
A가 질문에 답하고 전체 방향·대상별 지시·필요한 망 변경을 정함
  ├─ 필요한 경우 기존 부품으로 추가 정보/창·탭/Work 준비
  └─ bct_set_direction(action="save", assessment=판단, direction_text=방향)
  ↓
bct_chain_message(action="start", chain_direction_id=기록한 방향)
  ├─ 기록한 망 변경을 기존 bct_set_conversation_network로 적용
  ├─ 현재 A Manager / 전역 Supervisor 한 명 / 각 대상 재확인
  └─ 지금 실행할 각 대상 B/C/D에 대해
       ├─ 해당 대상만의 지시와 Direction 연결 기록
       ├─ 같은 대화 UUID의 현재 RCC 탭·창·세션 재확인
       ├─ 기존 Delayed Send 감시 선등록
       └─ 기존 send-message로 정확히 한 번 전송
  ↓ 실제 대상의 새 판단 턴
B/C/D가 자기 범위의 구체적인 계획을 세움
  └─ bct_set_execute_plan으로 해당 Direction/Task/generation에 기록
     → 필요한 부품·모듈·프로그램으로 실제 실행
     → NEXT TASK — SELF: 다음 작업 / MANAGER: 반환 지시
  ↓ 백그라운드 감시기
응답 출처·완료·입력 가능 상태와 분기 확인
  ├─ SELF → 같은 대상에 다음 턴 전달, 기존 계획·맥락 연결
  └─ MANAGER → A에게 결과 반환
                 ↓
계속할 경우 A가 bct_chain_message(action="prepare",
 source_kind="MANAGER_RETURN", source_task_id=..., source_generation=...) 재호출
현재 현실부터 다시 읽고 다음 방향을 판단
```

하나의 도구 호출이 A와 B의 여러 AI 턴을 내부에서 대신 실행한다는 뜻이 아니다.
입구가 조회와 질문 제공을 호출하고, **호출한 AI가 판단 결과로 다음 단계를 진행**한다.
일반 Chat에서도 같은 MCP 명령을 호출할 수 있으면 같은 계약을 쓴다.
Codex 전용 computer-use나 숨은 외부 오케스트레이터를 호출하지 않는다.

## Set Direction: 질문 → A 판단 → 결과 기록

`bct_set_direction(action="prepare")`는 독립적으로 재사용할 수 있다. 질문은
사용자에게 떠넘기는 설문지가 아니라 **A가 답할 내부 검토 항목**이다.

| 질문 | A가 결정할 내용 |
| --- | --- |
| 사용자 의도 | 원래 요청 또는 반환 보고를 사용자 목표에 맞게 정제 |
| 완료 기준 | 완료·미완료·미확인, 요구할 실제 증거 |
| 범위와 조건 | 우선순위·금지사항·보존 대상·확인할 불명확한 부분 |
| 대화망 | 열린 Node Info와 저장된 이력 비교, 재사용·신규·병합 판단 |
| Manager | 지시받은 A의 역할, 기존 Manager 역할 해제·승계 |
| Supervisor | 전역 한 명 유지, 부재·닫힘·복수 역할 정리 |
| 대상별 분담 | AB/AC/AD 수와 각각의 지시, 독립/선행 의존 작업 구분 |
| 자율 선택 | 부품·블럭·레시피·PowerShell·프로그램·BDC·창/탭 기능, B 재량 |
| 정체·승계 | Check Node → Recheck Node → Pause Node → Replace Node → Reset Node, 기존 영수증 보존 |
| 검증·반환 | Supervisor 통합 검토, CI 알람, 배포/E2E 순서·rollback·반환 조건 |

save는 `assessment.answers`의 모든 답, Manager/Supervisor UUID, 대화망 이름,
대상별 `{conversation_key, role, instruction}`, `network_updates`를 검증하고
원문과 함께 기록한다. 같은 Direction ID의 내용 변경은 거부한다.
`bct_get_direction`으로 판단과 대상별 Task/Operation 연결을 함께 읽는다.
USER의 원문은 `CALLER_PROVIDED_TEXT`다. 호출자가 제공한 문자열이며 인증된 사용자 턴을
직접 읽었다는 증거가 아니다. MANAGER_RETURN은 정확한 원장·응답 해시를 확인한 뒤
`VERIFIED_MANAGER_RETURN`으로 표시한다. 두 출처의 증거 수준을 같게 취급하지 않는다.

질문에 성실히 답했는지를 문자열 검사만으로 증명할 수는 없다. BCT가 검증하는
것은 필수 답의 존재, 구체적 식별값·역할·소속·입력 계약·동일 영수증 등의 조건이다.
다른 AI 노드의 검토 및 실제 결과 검증은 여전히 필요하다.

## 망 준비와 1:N

- 망은 무조건 새로 만들지 않는다. A가 현재 Node Info(우클릭 정보)와 저장된 이력을
  비교하여 재사용·신규·병합과 역할 승계를 결정한다.
- `network_updates`는 기존 `bct_set_conversation_network` 인수 목록이다.
  `node-info-set`에는 관찰한 `expected_scope_id`와 `expected_role_tags_sha256`도
  기록하여 뒤늦게 사용자 변경을 덮어쓰지 않는다.
- 창·탭이 없으면 A가 기존 생성·복구 부품으로 준비하고 실제 대화 UUID를 얻는다.
  새 브라우저를 몰래 열거나, 제목으로 UUID를 추측하지 않는다.
- Supervisor가 없거나 복수이면 A가 기존 설정/복구 기능으로 준비·정리한다.
  현재 관찰이 그 판단과 일치하기 전에는 전송하지 않는다. 준비 필요는 영구 차단이
  아니라 같은 Direction을 안전하게 재확인할 수 있는 상태다.
- `targets`에는 **지금 독립적으로 시작 가능한 대상만** 넣는다. 선행 구현 결과가
  필요한 병합·배포는 같은 목록에 미리 실행시키지 않고 BA 뒤 새 Direction에서 C에게 맡긴다.
- 하나의 A 방향 아래 대상별 Direction/Task/Operation이 따로 연결된다. 이것은
  기존 정확 1:1 전송 원장을 재사용하기 위한 내부 기록이며 새 사용자 명령이 아니다.
- 특정 대상만 진행하려면 같은 Direction과 Task/Operation 접두사에
  `target_conversation_key`를 지정한다. 이미 시작한 대상은 재전송하지 않는다.
- 망 변경 전 모든 필요한 대상의 현재 연결을 먼저 검사하고, 변경 후 역할·소속을
  재검사한다. 그 사이 창이 닫힐 수 있으므로 전체 과정은 단일 원자적 효과가 아니다.
  `network_results`, `network_preparation_applied`, `all_targets_started`로 부분 효과와
  전송 결과를 구분한다. 적용된 망 변경을 지우거나 자동으로 되돌리지 않는다.

## Work와 권한

Work는 작업 루트·허용 기능·소유자 등을 보존하는 기존 실행 경계다. 노드, 대화망,
ChatGPT Work 모드, 한 번의 Task ID와 다르며 이름이나 기존 ID를 바꾸지 않는다.
초기 정보 조회에는 Work가 없어도 된다. 효과를 만들기 전에는 A가 기존 Work를
확인해 재사용하거나 `bct_create_work`로 요청 범위에 맞게 준비한다.

망 변경에는 기존 `conversation_network_update`, 전송에는 기존 `browser` 권한이
필요하다. 레시피가 기존 Work 권한을 자동으로 넓히지 않는다.

## 감시와 반환

감시기는 BCT 백그라운드 런타임에서 일한다. A가 화면을 붙잡고 기다리는 방식이
아니므로 사용자와 대화하거나 다른 독립 작업을 진행할 수 있다. WATCHING은
정확한 원 전송에 대응하는 응답 완료를 기다리는 상태이며 작업 완료 증거가 아니다.

각 대상에는 SELF/MANAGER 명시 출력 계약을 붙인다. 그 **동일한 원문**이 감시
선등록과 실제 전송에 사용된다. 기본 `max_generations=0`은 고정 반복 한도 없음이다.
진전·위험·완료 여부는 B가 판단하며, 사용자/A가 명시한 예산만 선택적으로 제한한다.

마커 누락·충돌·출처 불일치가 생기면 시스템이 거짓 후속 지시를 만들어내지 않는다.
기존 감시 진단 및 Manager 검토 경로로 보존한다. UNKNOWN은 새 ID로 재전송하지 않는다.
여러 대상 중 일부만 실패하면 이미 시작한 대상의 영수증은 유지하고 미확정 대상만 표시한다.

BA/CA 반환을 새 방향으로 다듬을 때 정확한 Work·Task·generation·응답 해시를 결합한다.
A는 `COMPLETE`, `NEW_TASK`, `ASK_USER`, `HOLD`를 판단한다. NEW_TASK가 메인 병합·CI·
배포·E2E라면 대상 C와 그 지시를 같은 `targets`에 기록하여 범용 흐름을 재사용한다.

## 기존 경로와 검증 경계

- 이미 정확한 대상·지시를 가진 기존 호출은 종전 send/watch 경로를 유지한다.
  기존 자유문 Direction은 보존하지만 새 질문 검토를 거친 것으로 표시하지 않는다.
- 기존 `bct_prepare_supervisor_chain` 기록과 과거 ID는 삭제하지 않는다. 새 질문 기반
  흐름은 그 특수 경로를 호출하지 않고 같은 대상별 전송 경로로 C를 처리한다.
- `bct_set_execute_plan` / `bct_get_execute_plan`은 B가 작성한 정확한 계획의
  저장·조회와 같은 Chain의 SELF 맥락 연결이다. 임의 프로그램을 실행하는 명령이 아니다.
  A의 전송 성공만으로 B가 계획을 작성·저장했다는 사실까지 증명되지는 않는다.
- 기존 `bct_run_task`, `bct_plan_run`, `bct_set_project_plan`은 별도 기능이다.
  이 레시피는 그들을 숨은 실행기로 호출하지 않으며 `bct_run_execute_plan`을 새로 만들지 않는다.
- `action="preflight"`는 읽기 전용이다. 망 변경을 미리 적용하지 않으므로 준비가
  안 된 망은 `NETWORK_PREPARATION_REQUIRED`로 반환한다. READY도 실제 전송 성공은 아니다.

소스 회귀 검증: `tests/test_direction_review.py`, `tests/test_chain_direction.py`,
`tests/test_chain_message_preflight.py`와 기존 Chain/네트워크/복구/MCP 테스트.
브라우저 효과를 모의한 격리 테스트와 실제 일반 Chat LIVE E2E는 구분해서 보고한다.
