# Chain Recipe 공통 설명서

Chat·Work·Codex에서 같은 BCT 연결을 쓰면 같은 설명서와 도구 계약을 확인할 수 있다.
소스 옆에서 볼 때는 이 파일을 열고, 일반 Chat에서는 `bct_capabilities(include_manual=true)`를 호출한다.
설치된 설명서의 `manual.sha256`과 소스 파일의 UTF-8/LF 해시를 비교하면 같은 내용인지 확인할 수 있다.

[실제 흐름](#실제-호출-흐름) · [이름과 역할](#이름과-역할) ·
[부품 찾기](#필요한-부품과-도구-찾기) · [응답 대기와 반환](#응답-대기와-반환) · [갱신 방법](#설명서-갱신과-검사)

## 바로 시작하는 노드 안내

일반 작업의 기본 입구는 `bct_chain_recipe`다. Task Message / Send Message를 사용자가
명시한 경우에만 그 별도 경로를 사용한다. 이 안내는 역할 지정이나 실행 권한을 새로 부여하지 않는다.

- A: `bct_chain_recipe(instruction=요청)` → 현재 현실·대화망과 내부 질문 확인 →
  A가 의도·완료 기준·대상별 지시·필요한 망 변경을 판단 →
  같은 `bct_chain_recipe(action="save", entry_context_id=준비 결과, assessment=판단, ...)` →
  `bct_chain_recipe(action="send", direction_id=저장한ID, ...)`.
  질문은 A가 답한다. 사용자에게 사용법이나 질문지 작성을 떠넘기지 않는다.
- 전달받은 B/C: 이 지시의 수신자로서 지정된 범위만 처리한다. 새 Manager를 자칭하지 않는다.
  현재 환경을 읽고 세부 계획을 세워 `bct_set_execute_plan`으로 전달받은
  Work·Direction·Task·generation에 연결한다. 필요한 부품은 직접 선택하되 기존 권한을 넘지 않는다.
- 응답 끝: 진전이 있고 계속할 일이 있으면 `NEXT TASK — SELF: 다음 지시`,
  완료·위험·정체·판단 필요이면 `NEXT TASK — MANAGER: 결과와 반환 지시` 중 하나를 남긴다.
  고정 횟수만으로 왕복하지 않는다. 응답 감시는 BCT 백그라운드가 담당하므로 A가 붙잡혀 기다리지 않는다.
- BA/CA를 받은 A: 정확한 반환 Task/generation으로 Chain Recipe의 prepare에 다시 들어가
  현재 상태와 방향을 재검토한다. 반환이 선언된 Direction에서 온 경우 prepare 결과의
  `return_chain_link`가 원래 Direction·Task·generation을 보여 주며, 같은 entry_context로
  save하면 다음 Direction은 그 부모에 자동 연결된다. 다른 부모로 바꾸어 저장할 수 없다.
  필요한 병합·배포·E2E는 Supervisor에게 별도 지시한다.
- B/C가 관찰·진단·수정·검증의 추가 작업을 제안할 때는 `bct_chain_branch(action="request")`에
  현재 Root Work, 부모 Direction/단계, Task/generation, 이유와 정확한 영수증 참조를 남긴다.
  이는 **자식 지시나 전송을 만들지 않는 보고**다. A만 Chain Recipe를 처음부터 다시 들어가
  `bct_chain_recipe(action="save", entry_context_id=..., branch_request_id=...)`으로 이를 채택하고, 저장 뒤에는 반드시 그 Direction의 Chain Recipe를
  시작한다. `bct_chain_branch(action="tree")`와 `bct_status`의 주의 목록은 이 연결과 다음
  안전 단계를 읽을 뿐 판단·전송하지 않는다.
- 사용법이 불명확하면 `bct_capabilities(tool_name="사용할 실제 명령")`으로 현재 입력 계약을 읽고,
  `query="필요한 기능"`으로 부품을 찾는다. 전체 설명서는
  `bct_capabilities(include_manual=true)`이며 로컬 파일 접근 없이 일반 Chat에서도 읽을 수 있다.
- UNKNOWN은 새 ID로 재전송하지 않는다. 소스·테스트·CI·main·설치·LIVE 증거를 구분한다.
  이 설명서는 배포된 소스의 사용법이지 해당 작업의 완료 증거가 아니다.

## 이 문서의 범위

이 문서는 **이 체크아웃의 소스 동작**을 설명한다. 테스트 통과는 main 병합·설치·
LIVE 검증의 증거가 아니다. 실행 중인 버전은 Core 상태와 정확한 영수증으로 별도 확인한다.

## 기본 운영 방침: 제한보다 관찰과 부분 진행

중요하지 않거나 실제 효과 안전에 필요하지 않은 제한은 기본적으로 두지 않는다.
역할, 대화망 모양, 처리 순서, 과거 경로, Work/세대의 참고값은 A가 판단할 때 읽는
정보이며 그 자체로 전송을 막는 권한 장치가 아니다. 대상 하나가 현재 닫혀 있으면
다른 정확한 대상의 전송은 계속하고, 닫힌 대상만 그 사실을 결과로 남긴다.

유지하는 제한은 세 가지뿐이다. 같은 대화 UUID가 아닌 곳으로 임의 전환하지 않기,
UNKNOWN 외부 효과를 새 ID로 재전송하지 않기, 이미 발생한 효과의 영수증을 덮어쓰지
않기다. 같은 UUID가 다른 탭/창으로 이동한 경우에는 현재 관찰로 다시 결합한다.
다른 대화 노드가 필요하면 A가 다음 Direction에서 그 UUID를 명시한다.

대표 입구는 `bct_chain_recipe`다. 일반 작업 요청은 이 입구를 사용한다.
사용자가 Task Message 또는 Send Message를 명시한 경우에만 그 방식을 직접 쓴다.
`bct_task_message`는 사용자 방향을 다듬는 Set Direction의 다른 이름이 아니다.

## 실제 호출 흐름

```text
사용자의 요청 또는 정확한 BA/CA 반환
  ↓
bct_chain_recipe(instruction=요청) 또는 action="prepare"
  └─ 현재 A의 정확한 UUID를 알고 있으면 `origin_conversation_key`로 함께 넘김
  └─ bct_chain_recipe(action="prepare") 내부 호출
      ├─ 현재 Core/런타임/Work/작업 영수증/CI Inbox 조회
      ├─ bct_check_conversation_network 내부 호출
      │    열린 Node Info + RCC + 저장된 대화망 이력
      ├─ 해당 A UUID가 제공된 경우 그 A의 `Recovery Notices` Wake 기록 조회
      ├─ 같은 Work·A UUID에 정확히 연결된 `GitHub CI Notices` 조회
      │    └─ 완료 결과를 보여 줄 뿐, 자동 전송·재시도·다음 Direction 작성은 하지 않음
      └─ A가 판단할 내부 질문·사용 가능한 대표 명령 목록·부품 검색 사용법 반환
  ↓ 실제 A의 판단 턴 — BCT가 AI 대신 생각하지 않음
A가 현재 Work tree·영수증·Node Info를 본 뒤 질문에 답하고 전체 방향·대상별 지시·필요한 망 변경을 정함
  ├─ 필요한 경우 기존 부품으로 추가 정보/창·탭/Work 준비
  └─ 같은 Chain Recipe의 `entry_context_id`로
     `bct_chain_recipe(action="save", entry_context_id=..., assessment=판단, direction_text=방향)`
  ↓
선택: Direction에 `node_recovery: {conversation_key: 정확한 UUID}`가 있을 때만
Recover Node R
  ├─ Check Node R — 해당 노드의 현재 신호를 기록
  └─ State R 다시 읽기 — 복구 확인 뒤에도 현재 현실을 다시 봄
  └─ Pause / Replace / Reset은 자동 실행하지 않음. 필요하면 A가 별도 부품을 명시적으로 선택
  └─ 감시 중인 노드가 반복 중단되면 BCT는 해당 A 반환 UUID의 `recovery_notices`에
     `RECOVERY_NEEDED` Wake 기록만 남김. A가 읽고 다음 Direction을 작성하며,
     BCT는 자동 재전송·새 Chat 생성·교체를 하지 않음.
  ↓
bct_chain_recipe(action="send", direction_id=기록한 방향)
  ├─ 기록한 망 변경을 기존 bct_set_conversation_network로 적용
  ├─ A의 반환 대화와 각 선언 대상의 현재 UUID·탭·창 재확인
  └─ 지금 실행할 각 대상 B/C/D에 대해
       ├─ 해당 대상만의 지시와 Direction 연결 기록
       ├─ 같은 대화 UUID의 현재 RCC 탭·창·세션 재확인
       ├─ BCT의 응답 대기 기록 생성
       └─ 기존 send-message로 정확히 한 번 전송
  ↓ 실제 대상의 새 판단 턴
B/C/X/S가 자기 범위의 구체적인 계획을 세움
  └─ bct_set_execute_plan으로 해당 Direction/Task/generation에 기록
     → 필요한 부품·모듈·프로그램으로 실제 실행
     → 한 계획 revision의 N/N은 자동 반환 조건이 아님
     → Direction이 아직 미완료면 같은 plan_id를 update하여 다음 bounded phase를 만들고 SELF
     → 대상이 완료·위험·정체·A 판단 필요를 판단한 경우에만 MANAGER 반환
  ↓ BCT 백그라운드 응답 처리
응답 발견 기록 후 출처·완료·입력 가능 상태와 분기 확인
  ├─ SELF → 같은 대상에 다음 턴 전달, 기존 계획·맥락 연결
  └─ MANAGER → A에게 결과 반환
                 ↓
A 장애 중 Manager 반환 보존
  ├─ Direction의 전역 Supervisor UUID를 첫 Watch부터 recovery collector로 결속
  ├─ Worker의 MANAGER 반환을 원 Work/Direction/Task/generation에 먼저 체크포인트 저장
  ├─ A가 정확히 연결 중이면 A에게 그대로 반환
  ├─ A의 PAUSED/연결 끊김이 확인된 경우에만 S에게 인계 정보로 전달
  │    └─ S는 판단·완료·재지시하지 않고 반환 원문과 식별값만 보관
  ├─ A 상태가 애매하거나 전송 효과가 UNKNOWN이면 S로 우회 재전송하지 않음
  ├─ S 또는 복구된/후임 A는 action="recovery_inbox"로 마지막 실행 결과와
  │    동일 전송 영수증을 읽음
  ├─ 기존 진행 Watch는 action="bind_recovery_collector"로 전송 없이 보강
  ├─ 기존 A 복구 또는 대화망에서 정식 Manager 승계가 확인된 뒤
  │    action="resume_manager"로 활성 Watch와 미확인 체크포인트의 A 결속만 변경
  └─ A가 각 체크포인트를 읽고 action="ack_recovery"한 뒤 State R에서 다음
       Direction을 판단함. ACK 전에는 복구 완료로 보지 않음
                 ↓
계속할 경우 A가 bct_chain_recipe(action="prepare",
 source_kind="MANAGER_RETURN", source_task_id=..., source_generation=...) 재호출
현재 현실부터 다시 읽고 다음 방향을 판단
  └─ 선언된 Direction에서 온 정확한 반환이면 다음 save는 원래 Direction에
     `MANAGER_RETURN` 연결을 자동 기록한다. 읽기는 반복해도 전송·생성은 반복하지 않는다.
```

`recovery_inbox`, `bind_recovery_collector`, `resume_manager`, `ack_recovery`는 원 Worker
작업이나 UNKNOWN 효과를 재실행하지 않는다. 누락 상태 확인은 원 작업 재지시가 아닌 별도의
읽기 전용 확인 Direction으로 작성한다.

### 추가 분기와 원래 체인 복귀

```text
원래 B Direction의 정확한 Task/generation
  └─ B의 branch request (관찰/진단/수정/검증; 전송 없음)
       └─ A가 채택한 BA Direction → 일반 Chain Recipe → BA 결과
            ├─ 필요하면 같은 방식으로 BAA/BBB 요청과 채택
            └─ A가 원래 B Direction의 `RESUME` Direction을 저장 → 일반 Chain Recipe 재시작
```

각 노드는 Root Work, 부모 Work/Direction/Recipe 단계, 종류, 시작 이유, Task·Operation·전송
영수증·대화 UUID 참조, 현재 상태·근거·다음 안전 단계를 보존한다. `READY`, `IN_PROGRESS`,
`WAITING_INPUT`, `WAITING_EXTERNAL`, `IDENTITY_MISMATCH`, `CHECK_FAILED`, `NOT_APPLIED`,
`UNKNOWN`, `BLOCKED`, `COMPLETED`를 구분한다. 독립된 형제는 진행을 계속할 수 있지만, A는
필수 자식이 해결·명시적 완료·차단 처리되기 전 Root를 완료로 표시하지 않는다. `UNKNOWN`은
항상 같은 영수증으로만 조정하며 새 메시지나 대체 Operation을 재전송하지 않는다.

하나의 도구 호출이 A와 대상 노드의 여러 AI 턴을 내부에서 대신 실행한다는 뜻이 아니다.
입구가 조회와 질문 제공을 호출하고, **호출한 AI가 판단 결과로 다음 단계를 진행**한다.
일반 Chat에서도 같은 MCP 명령을 호출할 수 있으면 같은 계약을 쓴다.
Codex 전용 computer-use나 숨은 외부 오케스트레이터를 호출하지 않는다.

## Set Direction: 질문 → A 판단 → 결과 기록

`bct_set_direction(action="prepare")`는 과거 호출자를 위한 **읽기 전용 준비 별칭**이다. Direction 저장은 이 별칭으로 할 수 없고, 항상 `bct_chain_recipe`의 prepare → save 순서로만 한다. 질문은
사용자에게 떠넘기는 설문지가 아니라 **A가 답할 내부 검토 항목**이다.

| 질문 | A가 결정할 내용 |
| --- | --- |
| 사용자 의도 | 원래 요청 또는 반환 보고를 사용자 목표에 맞게 정제 |
| 완료 기준 | 완료·미완료·미확인, 요구할 실제 증거 |
| 범위와 조건 | 우선순위·금지사항·보존 대상·확인할 불명확한 부분 |
| 대화망 | 열린 Node Info와 저장된 이력 비교, 재사용·신규·병합 판단 |
| A 반환 대상 | 이번 Chain 결과가 돌아올 정확한 A 대화 UUID. 역할 라벨과 별개 |
| 대상 역할 라벨 | `worker`·`reviewer`·`deployer` 등 A가 붙이는 설명용 이름. 전송 권한이나 전역 단일성을 만들지 않음 |
| 대상별 분담 | AB/AC/AD 수와 각각의 지시, 독립/선행 의존 작업 구분 |
| 자율 선택 | 부품·블럭·레시피·PowerShell·프로그램·BDC·창/탭 기능, B 재량 |
| 정체·승계 | Check Node가 기존 DOM·연결·진행 신호를 조합 → Recheck Node가 변화 비교 → 필요한 경우에만 후속 복구, 기존 작업 영수증 보존 |
| 검증·반환 | Supervisor 통합 검토, CI 알람, 배포/E2E 순서·rollback·반환 조건 |

### 통합 CI 책임

Worker는 자신의 Worktree에서 필요한 로컬 검증과 변경·증거 보고를 한다. 개별 Worker가
PR이나 `main` push를 만들지 않는 한 GitHub CI는 시작되지 않는다. Supervisor가 통합 PR과
`main` 병합을 맡는다. PR은 범위·설명서 일치만 확인하고, 병합 뒤의 정확한 `main` revision에서
6분할 Core CI와 필요한 E2E를 Supervisor가 확인한 뒤 A에 반환한다. CI 결과는 역할 라벨이
아니라 그 CI를 등록한 정확한 실행 대상 Work·대화 UUID에 연결한다.

save는 필요한 경우에만 기록한 `assessment.answers`, A의 반환 대화 UUID, 선택 메타데이터,
대상별 `{conversation_key, role, instruction}`, `network_updates`를 검증하고
원문과 함께 기록한다. 같은 Direction ID의 내용 변경은 거부한다.
`bct_get_direction`으로 판단과 대상별 Task/Operation 연결을 함께 읽는다.

`conversation_key`는 Monitor 번호(`N96`)나 창 제목이 아니라 소문자 canonical 대화 UUID다.
`targets`의 허용 키는 정확히 `conversation_key`, `role`, `instruction`이고 역할은
`worker`, `reviewer`, `deployer`처럼 A가 붙이는 자유 라벨이다. 기존 대화망을 그대로 재사용하면 `network_updates: []`가
정상이다. 저장 실패 응답의 `assessment_contract`는 누락된 질문 키, 잘못된 대상의
인덱스·허용 키, UUID/역할 규칙과 같은 Direction ID로 안전하게 재시도하는 방법을 돌려준다.
`entry_context_id`는 이번 prepare에서 읽은 정확한 입력 결속과 현재 Root Work tree의
식별값이다. 새 관계 저장소나 권한 토큰이 아니다. 저장 직전에 반환·분기·영수증 상태가 바뀌면
저장은 `CHAIN_RECIPE_REENTER_REQUIRED`로 멈추고, Manager에게 최신 State R을 다시 돌려준다.
저장 성공 뒤에는 반드시 `bct_get_direction`으로 Direction ID와 기록된 대상·판단을 읽고
그 ID로 시작한다.
USER의 원문은 `CALLER_PROVIDED_TEXT`다. 호출자가 제공한 문자열이며 인증된 사용자 턴을
직접 읽었다는 증거가 아니다. MANAGER_RETURN은 정확한 원장·응답 해시를 확인한 뒤
`VERIFIED_MANAGER_RETURN`으로 표시한다. 두 출처의 증거 수준을 같게 취급하지 않는다.

질문은 A의 내부 판단 안내이며 저장을 허가하는 설문 관문이 아니다. `assessment.answers`는
전부 생략하거나 필요한 판단 근거만 기록할 수 있다. BCT가 검증하는 것은 실제 실행에
필요한 구체적 대화 UUID·입력 계약·동일 영수증 등의 조건이다. 새 Chain Recipe의 첫
전송에는 Manager·초기 Worker·전역 Supervisor의 서로 다른 UUID와 현재 역할/대화망
관계도 실행 조건이다. 이후 대상별 실제 실행 판단은 그 위에서 계속 분리한다.

## Recover Node R: 선택형 노드 복구 점검

`Recover Node R`은 “복구 담당 노드”가 아니라 **하나의 노드를 복구 흐름으로 점검하는
부분 레시피**다. Direction의 선택 필드 `node_recovery`에 정확한 대화 UUID 하나를 기록할 때만
실행한다. 구성은 `Check Node R → State R 재읽기`다.

현재 이 레시피는 복구 필요 신호를 기록하고 최신 상태를 돌려줄 뿐이다. `Pause Node`,
`Replace Node R`, `Reset Node R`은 브라우저 전송·승계·탭 닫기 같은 외부 효과가 있으므로
이 레시피가 알아서 실행하지 않는다. A가 그 다음 Direction 또는 명시적 부품 호출로 선택한다.
다른 AI 노드의 검토 및 실제 결과 검증은 여전히 필요하다.

## 망 준비와 1:N

- 망은 무조건 새로 만들지 않는다. A가 현재 Node Info(우클릭 정보)와 저장된 이력을
  비교하여 재사용·신규·병합과 역할 승계를 결정한다.
- `network_updates`는 기존 `bct_set_conversation_network` 인수 목록이다.
  `set-node-info`에는 관찰한 `expected_scope_id`와 `expected_role_tags_sha256`도
  기록하여 뒤늦게 사용자 변경을 덮어쓰지 않는다.
- 창·탭이 없으면 A가 기존 생성·복구 부품으로 준비하고 실제 대화 UUID를 얻는다.
  새 브라우저를 몰래 열거나, 제목으로 UUID를 추측하지 않는다.
- 새 Chain Recipe는 시작 전에 Manager와 초기 Worker가 같은 대화망에 있고, 전역
  Supervisor가 하나이며 세 역할이 서로 다른 열린 UUID인지 확인한다. 하나라도
  미확인이면 `NETWORK_PREPARATION_REQUIRED`로 멈추며, A가 기존 대화망 설정/복구
  부품으로 바로잡은 뒤 같은 Direction을 다시 확인한다. 이는 역할에 따른 권한 장벽이
  아니라 잘못된 토폴로지로 체인을 시작하지 않기 위한 시작 검증이다.
- `targets`에는 **지금 독립적으로 시작 가능한 대상만** 넣는다. 선행 구현 결과가
  필요한 병합·배포는 같은 목록에 미리 실행시키지 않고 BA 뒤 새 Direction에서 C에게 맡긴다.
- Manager가 `derived_tasks`를 기록하면 각 항목은 `SELF`, `INDEPENDENT`, `BLOCKED`,
  `RISK`, `ASK_USER` 중 하나로 분류한다. `INDEPENDENT`만 정확히 선언된 대상 UUID와
  연결해 이번 Direction에서 병렬 시작할 수 있다. 선행 `depends_on`, 위험·사용자 판단,
  SELF 연속은 저장된 근거로 남기고 전송하지 않는다. 두 독립 작업이 같은
  `mutable_scopes`를 선언하면 Direction 저장을 거부한다. 이 검사는 Manager의 판단을
  대신하거나 완료된 선행 효과를 추측하지 않는다.
- 하나의 A 방향 아래 대상별 Direction/Task/Operation이 따로 연결된다. 이것은
  기존 정확 1:1 전송 원장을 재사용하기 위한 내부 기록이며 새 사용자 명령이 아니다.
- 추가 Worker가 필요하다고 A가 판단한 경우 `bct_chain_recipe(action="provision_worker")`는
  별도 공개 도구를 만들지 않고 기존 `create-chat-tab`/`create-chat-window`, `send-message`,
  응답 대기, `set-node-info`, 선택적 `move-tab`을 부분 레시피로 조립한다. 생성·전송·감시·
  등록·정렬은 서로 다른 결정적 Operation ID와 영수증을 사용한다. 같은 준비 요청을
  재실행해도 기존 영수증을 읽으며 새 탭이나 첫 메시지를 중복 생성하지 않는다.
- A의 준비 판단은 Direction의 `worker_preparations`에 먼저 저장한다. 각 준비 항목은
  `preparation_id`, 생성 명령과 대상 RCC instance/window, 대상별 instruction, Node Info,
  선택적 정렬 위치를 보존한다. 실행할 때는 저장된 `preparation_id`만 선택하므로 재시작한
  호출자가 생성·역할·지시 내용을 다르게 바꿀 수 없다. 기존 Worker가 충분하면 이 목록을
  만들지 않고 기존 `targets` 경로를 그대로 사용한다.
- 새 빈 Chat은 첫 전송 전 대화 UUID가 없을 수 있다. 이때 생성 영수증으로 정확한 탭에만
  첫 메시지를 한 번 제출하고, 그 전송 영수증에서 얻은 UUID와 현재 RCC 탭이 일치한 뒤
  기존 응답 대기 원장에 0회 기준점으로 결합한다. UUID가 없거나 탭이 일치하지 않으면
  `WAITING_FOR_CONVERSATION_UUID`로 남기며 다른 탭에 보내거나 새 ID로 재전송하지 않는다.
- 탭 정렬은 응답 대기 기록이 영속화된 뒤 그 Worker UUID로 해당 탭 하나만 이동한다.
  사용자가 배치한 다른 탭은 이동하지 않는다. 정렬 실패는 이미 정확히 전달된 Child Task를
  취소하거나 다른 탭으로 우회하는 근거가 아니다.
- 특정 대상만 진행하려면 같은 Direction과 Task/Operation 접두사에
  `target_conversation_key`를 지정한다. 이미 시작한 대상은 재전송하지 않는다.
- 망 변경과 대상 전송은 부분 효과일 수 있다. 한 대상이 닫혀도 다른 열린 대상의 전송은
  계속하며, `network_results`, `network_preparation_applied`, `all_targets_started`로 결과를
  구분한다. 적용된 망 변경을 지우거나 자동으로 되돌리지 않는다.

## Work와 권한

Work는 작업 루트·의도한 기능·현재 실행 주체 등을 보존하는 지속 작업 기록이다. 노드, 대화망,
ChatGPT Work 모드, 한 번의 Task ID와 다르며 이름이나 기존 ID를 바꾸지 않는다.
초기 정보 조회에는 Work가 없어도 된다. 효과를 만들기 전에는 A가 기존 Work를
확인해 재사용하거나 `bct_create_work`로 요청 범위에 맞게 준비한다.

`actions`는 의도한 작업 범위를 설명하지만 두 번째 권한 목록으로 실행을 막지 않는다.
신뢰된 후속 노드는 앞선 Operation이 모두 terminal이면 같은 Work를 자동 승계한다.
실제 실행은 현재 Principal capability와 Core Policy를 따르며, 진행 중 Operation,
동일 Operation 영수증, 자원 충돌, UNKNOWN 재전송 및 고위험 승인은 계속 차단한다.
파일 효과의 Work root 경계도 유지한다.

## 응답 대기와 반환

사람이 읽는 공통 용어는 다음 네 단계다. 이는 창을 잠그거나 닫고 여는 절차가 아니다.

```text
전송 기록 생성 → 응답 대기 → 응답 발견 → 결과 기록
```

`Watch Alarm R`은 코드 안의 부분 레시피 이름이다. 사람에게는 “BCT의 응답 대기·응답 발견
처리”라고 설명한다. A는 대기하지 않고, BCT 백그라운드가 해당 전송의 다음 응답을 찾는다.
기록은 끝난 뒤에도 지우거나 해지하지 않고 결과가 추가된 이력으로 남는다.

공개 명령과 Python 함수는 `bct_send_delayed_message`, 구현 모듈은
`bct.send_delayed_message`, 새 내부 요청 command는 `send-delayed-message`다.
이전 `bct_delayed_send_message`는 공개 별칭으로 남기지 않는다. 오래된 클라이언트의
도구 목록은 갱신해야 한다. 이미 발급한 Operation/Task ID, DB 테이블, 감시·Claim 잠금
키와 기존 영수증은 변경하지 않으며, 기존 준비 요청의 옛 command는 이력 호환을 위해
실행 경계에서만 읽는다. 이름 변경은 감시·전송 정책 변경이 아니다.

응답 대기는 BCT 백그라운드 런타임에서 일한다. A가 화면을 붙잡고 기다리는 방식이
아니므로 사용자와 대화하거나 다른 독립 작업을 진행할 수 있다. WATCHING은
정확한 원 전송에 대응하는 응답 완료를 기다리는 상태이며 작업 완료 증거가 아니다.

감시 중 정확한 Worker 대화가 연결 끊김, 다시 보내기, 새 Chat 필요, 복구 필요를
연속 두 번 표시하면 BCT는 `RECOVERY_NEEDED` 영수증을 남긴다. 이때 BCT는 Worker에게
자동 재전송하지 않고, 새 Chat을 만들거나 역할·대화망을 승계하지도 않는다. 현재 보고
대상은 이 영수증을 읽어 `Recover Node R` Direction을 작성하고, 필요할 때만 Pause,
Replace, Reset을 명시적으로 선택한다.

각 대상에는 SELF/MANAGER 명시 출력 계약을 붙인다. 그 **동일한 원문**이 응답 대기 기록과
실제 전송에 사용된다. 기본 `max_generations=0`은 고정 반복 한도 없음이다.
진전·위험·완료 여부는 대상 노드가 판단하며, 사용자/A가 명시한 예산만 선택적으로 제한한다.

SELF로 같은 대상에게 다음 회차가 전달되면 대상은 메시지에 표시된 정확한
`bct_send_delayed_message(work_id=..., task_id=...)`를 먼저 호출한다. 다음 세대에는
이전 정확 전송의 대상·Manager·RCC 결합이 이미 예약되어 있으므로 창·탭이나 target을
다시 고르지 않으며 범용 execute capability를 사용하지 않는다. 선예약이 APPLIED인 것을
확인한 뒤 작업을 시작해야 다음 응답도 같은 Task의 감시와 BA/BB 분기에 결합된다.

마커 누락·충돌·출처 불일치가 생기면 시스템이 거짓 후속 지시를 만들어내지 않는다.
기존 감시 진단 및 Manager 검토 경로로 보존한다. UNKNOWN은 새 ID로 재전송하지 않는다.
여러 대상 중 일부만 실패하면 이미 시작한 대상의 영수증은 유지하고 미확정 대상만 표시한다.

BA/CA 반환을 새 방향으로 다듬을 때 정확한 Work·Task·generation·응답 해시를 결합한다.
A는 `COMPLETE`, `NEW_TASK`, `ASK_USER`, `HOLD`를 판단한다. NEW_TASK가 메인 병합·CI·
배포·E2E라면 대상 C와 그 지시를 같은 `targets`에 기록하여 범용 흐름을 재사용한다.

## 기존 경로와 검증 경계

- 이미 정확한 대상·지시를 가진 기존 호출은 종전 send/watch 경로를 유지한다.
  기존 자유문 Direction은 보존하지만 새 질문 검토를 거친 것으로 표시하지 않는다.
- Chain Recipe 전송의 결과와 상태 영수증은 `execution_path`를 기록한다.
  `DIRECTION_DECLARED`는 저장된 `chain_direction_id`에 연결된 정식 경로이고,
  `DIRECT_EXACT_TARGET`은 Direction 없이 정확한 대상·지시를 명시한 호환 직접 경로다.
  직접 경로는 유효한 1:1 전송·감시일 수 있으나 대화망 판단이나 Direction 저장 성공을
  뜻하지 않는다. 과거 감시는 임의로 재분류하지 않고 `LEGACY_UNCLASSIFIED`로 읽는다.
- `bct_set_execute_plan` / `bct_get_execute_plan`은 수신 대상이 작성한 정확한 계획의
  저장·조회와 같은 Chain의 SELF 맥락 연결이다. 임의 프로그램을 실행하는 명령이 아니다.
  하나의 Direction/Task는 하나의 `plan_id`를 가지며, 여러 작업 phase는 새 계획 ID가 아니라
  `bct_update_execute_plan` revision으로 이어진다. 한 revision의 `N/N` 달성은 자동 반환이
  아니며, 수신 대상이 원 Direction의 완료 여부와 NEXT TASK를 판단한다.
  A의 전송 성공만으로 수신 대상이 계획을 작성·저장했다는 사실까지 증명되지는 않는다.
- 기존 `bct_run_task`, `bct_plan_run`, `bct_set_project_plan`은 별도 기능이다.
  이 레시피는 그들을 숨은 실행기로 호출하지 않으며 `bct_run_execute_plan`을 새로 만들지 않는다.
- `action="preflight"`는 읽기 전용이다. 망 변경을 미리 적용하지 않으므로 준비가
  안 된 망은 `NETWORK_PREPARATION_REQUIRED`로 반환한다. READY도 실제 전송 성공은 아니다.

소스 회귀 검증: `tests/test_direction_review.py`, `tests/test_chain_direction.py`와
기존 Chain/네트워크/복구/MCP 테스트.
브라우저 효과를 모의한 격리 테스트와 실제 일반 Chat LIVE E2E는 구분해서 보고한다.

## 이름과 역할

| 이름 | 이 소스에서 하는 일 |
| --- | --- |
| `bct_chain_recipe` | 전체 레시피의 입구. A 질문 준비 → A 판단 기록 → 대상별 정확 전송·감시 조합 |
| `bct_status` | 현재 Core·런타임·노드 등 종합 상태 조회 |
| `bct_get_conversation_network` | 저장된 대화망 정보 조회 |
| `bct_check_conversation_network` | 현재 관찰과 저장된 망 정보를 함께 점검. 조회가 망 변경을 뜻하지 않음 |
| `bct_set_conversation_network` | A가 결정한 망·역할·Node Info 변경을 기존 계약으로 적용 |
| `bct_chain_recipe` | 유일한 Chain Recipe 입구와 준비·Direction 저장·대상 전송 단계. prepare는 현재 Work tree를 Manager에게 보여 주고 save는 같은 entry_context_id를 요구 |
| `bct_set_direction` / `bct_get_direction` | 과거 호출자를 위한 읽기 전용 prepare 별칭 / 저장된 Direction 조회. 직접 저장은 불가 |
| `bct_chain_branch` | Worker의 연결된 분기 요청/상태 보고와 Root Work 트리 조회. 요청은 전송하지 않으며 A가 Direction으로 채택해야 한다. |
| `bct_set_execute_plan` / `bct_get_execute_plan` | 수신 대상이 생각한 세부 계획의 결합·저장과 조회. 계획 문장 자체를 실행하지 않음 |
| `bct_send_delayed_message` | 해당 작업의 응답 완료를 백그라운드에서 기다린 뒤 SELF/MANAGER 후속 지시를 전달하도록 등록 |
| `bct_context` | 특정 작업·회차의 이전 응답 증거, SELF/MANAGER 결정과 이어가기 기록 조회. 조회 자체는 감시하거나 전송하지 않음 |
| `bct_capabilities` | 현재 도구·입력 계약·부품·이 설명서 조회. 도구 실행이나 권한 부여는 아님 |
| Node Info | Monitor 우클릭 정보: 대화망·역할·담당 작업·메모. 관계의 정본은 Direction·branch·Watch 영수증이다. 자식/손자 지시에는 임시 관계 정보를 포함하고, Manager가 계속 참고할 짧은 상태가 필요하다고 판단하면 기존 `set-node-info`의 `node_memo`에 적을 수 있다. 메모만 바꿀 때는 현재 관찰한 `scope_name`·역할·기대 scope를 그대로 넣으므로 대화망 소속이나 역할은 바꾸지 않는다. BCT는 이 메모를 임의로 쓰지도, Manager의 명시적 기록을 막지도 않는다. |
| Work / task_id / Operation | 기존 지속 작업 경계 / 한 체인의 연속 처리 식별값 / 개별 효과와 영수증 |

Chain 전체 구현은 `src/bct/recipes/chain.py`에서 관리한다. 부분 레시피는 같은
`recipes/` 패키지의 `input.py`, `state.py`, `direction.py`, `network.py`, `delivery.py`,
`recovery.py`에 나뉜다. `outline.py`는 단계/진행 표시, `runtime.py`는 서버별 BCT·Principal·
상태 조회·기존 capability 실행기 연결 계약이다. 부분 레시피는 서버를 역으로 import하거나
MCP 도구를 등록하지 않는다. 기존 Direction/Watch/Operation 원장과 UNKNOWN 처리 경계를
그대로 사용하며, 파일 분리 자체가 배포나 LIVE 검증을 뜻하지 않는다.

읽기·변환 경계도 전송 코드와 분리한다. `discovery_views.py`는 실제 도구 메타데이터와
기존 부품 검색/RCC 목록을 조합하고, `status_queries.py`는 같은 snapshot의 상태와
저장된 대화망 조회를 담당한다. `project_plan.py`는 프로젝트 계획의 검증과 기록 형식
변환만 수행하며 저장은 기존 MCP 어댑터의 `project_context` 실행 경로가 맡는다.
`recipes/code_blocks.py`는 기존 Work 소유권·read·root 검사를 유지한 읽기 전용 스캔
조합이다. 이 분리는 공개명·입력/출력 계약·기존 효과 순서나 Loop 신규 시작 차단을 바꾸지 않는다.

공개 도구의 입구는 `src/bct/mcp_server.py`에 등록된다. 일부 보존된 공개명은 같은 내부 함수를
호출하므로 공개명과 내부 함수가 모두 1:1인 것은 아니다. 내부 재사용 함수·파일은 부품 조회의
`implementation`에서 확인한다. 새 이름을 추측하지 않는다.

## 필요한 부품과 도구 찾기

1. A는 Direction의 자율 선택 질문에서, B는 세부 계획을 작성하거나 수정할 때 필요한 기능을 찾는다.
   `bct_capabilities(query="코드 블럭")`, `query="데스크탑"`, `query="github_run_watch"`처럼 검색한다.
2. 결과의 부품 `contract`, `effects`, `safety`, `implementation`을 확인한다.
   `SOURCE_COMPONENT_ONLY`는 소스 내부 부품이지 직접 호출 가능한 MCP 도구가 아니다.
3. 실제 도구는 `bct_capabilities(tool_name="scan_code_blocks")`처럼 조회한다.
   `tool.inputSchema`는 **그 서버에 실제 등록된 계약**이다. 문서에 복사한 입력 예제가 아니다.
   compact 모드에서 capability를 간접 호출해야 하면 결과의 `capability_routes`에 실제 `bct_dispatch` 경로를 표시한다.
4. 필요한 것만 선택한다. A는 기존 `assessment.answers.resources`, B는 Execute Plan 본문에
   선택한 기능·이유·기대 결과를 남긴다. 실행 결과와 Operation 영수증은 기존 보고·맥락에 연결한다.
   검색 순위가 실행 결정은 아니며, 도구 목록 전체를 순서대로 실행하지 않는다.

부품 도서관은 `curated-not-exhaustive`다. 등록된 도구 전체와 분류를 마친 내부 부품의 범위는 다르다.
프로그램·PowerShell·BDC·브라우저 기능도 실제 제공되는 도구와 기존 Work 범위 안에서 선택할 수 있다.
새로운 기능·브리지 제작이나 외부 효과의 승인 규칙은 검색으로 바뀌지 않는다.

검색은 `limit`(1~20), `offset`, `next_offset`으로 나누어 읽는다.
`component_id`는 한 부품, `tool_name`은 한 도구의 상세 조회다. 라이브러리가 없는 구버전이면
사용 가능하다고 추측하지 말고 현재 `bct_capabilities` 결과를 기준으로 판단한다.

## 설명서 갱신과 검사

위의 노드 안내는 별도 사본으로 편집하지 않는다. `bct_capabilities` 기본 응답과
Chain/Set Direction의 prepare 응답에 `manual_guidance`로 자동 포함한다.
`bct_capabilities(tool_name="bct_chain_recipe")`에는 전체 설명서도 자동 포함된다.
새 질문 기반 방향의 수신자 지시에는 같은 안내·설명서 해시·조회 방법이 붙는다.
이미 기록한 대상 지시와 기존 직접 전송 원문은 재작성하지 않으며, 기존 SELF/BA 감시도 재등록하지 않는다.
설명서 번들이 없거나 손상되면 조회에 `UNAVAILABLE`을 표시하고, 안내가 필요한 새 대상 지시를
전송하기 전에 `MANUAL_GUIDANCE_UNAVAILABLE`로 알린다. 이미 기록된 지시는 보존한다.
일반 Chat·Work·Codex 모두 같은 MCP 응답을 받지만 클라이언트의 오래된 도구 설명은
연결/도구 목록 갱신이 필요할 수 있다. AI가 읽고 판단하는 단계까지 코드가 대신 실행하거나 보장하지 않는다.

원본은 이 파일과 `docs/component-library.v1.json`이다. Chat 전용·Work 전용·Codex 전용 설명서를
따로 편집하지 않는다. 배포용 `src/bct/data/component-library.json`은 두 원본과 관련 소스의
지문을 포함하는 생성물이며 Python 패키지와 Core 릴리스에 함께 포함된다.

흐름·질문·도구·부품 구현 변경 시 작업자는 설명서를 대조해 수정한 뒤
`python scripts/build_component_library.py --write --reviewed`로 생성물을 갱신한다.
`python scripts/build_component_library.py`와 `tests/test_component_library_discovery.py`가
문서·소스·생성물 불일치를 검사한다. CI의 scope 단계가 Core 검사 생략 여부를 정하기 전에
생성물 일치를 확인하므로 문서만 바꾼 경우에도 낡은 사본이 통과하지 않는다.
기계 검사는 낡은 사본과 누락을 찾으며, 설명 문장의 의미가 옳다는 것까지 자동 증명하지는 않는다.

실행 중인 서버는 자기 릴리스에 포함된 설명서를 돌려준다. 소스 설명서를 열었다고 LIVE가
업데이트된 것은 아니다. source fingerprint·manual hash, `bct_status`의 release SHA,
테스트·CI·설치·E2E 영수증은 각각 구분한다.

## 블록 조립형 영속 Loop

새 표준 Loop의 공개 입구는 `bct_persistent_loop_recipe`다. 아래의 보존된
`bct_loop_recipe`와 별개이며 Chain Recipe의 함수·명령·상태 전이는 변경하지 않는다.
사용자는 처리 블록과 `CONTINUE`, `WAIT`, `HANDOFF`, `COMPLETE`, `BLOCKED` 다섯 연결점만
선택한다. Watch, 정확한 신원, Operation 영수증, 재시작과 UNKNOWN 조정은 Loop 전용
연결 어댑터가 맡는다.

Supervisor가 아직 없으면 `action="prepare_supervisor"`가 기존 create-chat,
첫 정확 전송, bootstrap Delayed Send Watch, Node Info 기능을 변경 없이 조합한다.
새 대화 UUID는 첫 전송 뒤에 생기므로 이 준비만 생성·첫 전송 영수증을 확인한 뒤
zero-response Watch를 결속한다. 같은 Operation ID 재호출은 원 영수증을 읽을 뿐
새 대화나 메시지를 만들지 않는다. 준비 결과의 정확한 Supervisor UUID가 현재
관찰에서 확인된 뒤에만 `start`에 저장하고 새 Loop 대화망을 구성한다. 준비 시
노드는 미소속 `Loop Supervisor`로 등록되고 topology에서만 새 Loop 대화망으로
이동한다. 기존 Chain의 미소속 전역 `Supervisor` 태그와 규칙은 변경하지 않는다.

```text
outline
  -> start: 원 입력·Direction·정확한 A/S UUID·새 Loop 대화망 ID를 불변 저장
  -> topology: 새 대화망 생성 후 정확한 A=Manager, S=Supervisor 구성
  -> resume -> direction -> topology -> plan -> execute -> assess
       assess --CONTINUE--> plan
              --WAIT------> 현재 응답 Watch 선등록, 최초 자기 메시지 없음
              --HANDOFF---> Continuation 저장, 대상 Watch 선등록, 정확히 한 번 전달
              --BLOCKED---> 상태 보존과 Node Recovery
              --COMPLETE--> 완료 기록
  -> sync: 기존 Watch 결과만 읽어 재개; UNKNOWN이면 같은 영수증 조정
```

`WAIT`와 `HANDOFF`가 돌려주는 출력 계약은 기존 Delayed Send의 검증된
`NEXT TASK — SELF` / `NEXT TASK — MANAGER` 문법을 그대로 쓴다. Loop에서 MANAGER는
역할 이름이 아니라 반대쪽 결속 endpoint를 뜻한다. A의 MANAGER 반환은 S로, S의 MANAGER
반환은 A로 간다. 이 변환은 처리 블록 안에 들어가지 않는다.

`action="node_recovery"`는 기존 BCT Check/Recheck/Pause/Prepare Replace/Commit Replace
원장을 Loop 전용 어댑터에서 호출한다. 새 전송으로 복구하지 않는다. `UNKNOWN`은
`recovery_plan`과 원 Operation/Watch 조회로만 조정하며 같은 continuation ID의 중복 호출은
Watch나 메시지를 다시 만들지 않는다.

## 단일 Manager Loop의 독립 Supervisor 인계 (보존된 기존 명령)

현재 Chain 공통 코드 복원에 따라 새 `bct_loop_recipe(start)`는 기록 생성 전에
`LOOP_NEW_START_DISABLED_CHAIN_RESTORED`로 거절한다. 아래 Loop 내용은 기존 기록의
구조 설명이며 신규 실행 가능 안내가 아니다. 기존 기록·UNKNOWN·영수증은 보존한다.
복원된 Chain 계획 함수는 새 Loop/Loop 검수 계획 저장을 허용하지 않는다.

Loop 실행 노드는 자기 대화망의 Manager 하나이며 Worker나 손자 노드를 만들지 않는다.
별도 전역 Supervisor의 정확 UUID를 `bct_loop_recipe(start)`의 `supervisor`와
`review_instruction`으로 결속하거나, 기존 Loop에는 `configure_review`로 결속한다.
새 단일 노드 작업은 명시적인 `direction_text`와 Direction/Task ID를 start에 전달하면
같은 Direction 원장에 Loop 방향을 저장한다. 일반 Chain의 3노드 전송 검증을 완화하거나
가짜 Worker를 만들지 않는다. 기존 Direction은 덮어쓰지 않는다.
이 결속은 현재 역할과 망을 확인할 뿐 노드 생성·역할 변경·새 권한 부여를 하지 않는다.
Supervisor가 없거나 확인되지 않으면 시작/결속이 보류되며 다른 UUID로 대체하지 않는다.

결속된 Loop의 `complete(verified=true, candidate_sha=정확40자리SHA, evidence_text=증거)`
또는 `request_review`는 원 실행의 완료 조건을 확인하고 검수 대기만 기록한다.
Core는 동일 증거 패킷에 대해 기존 Send Delayed Message Watch를 선예약한 뒤 기존
BCT browser Operation으로 한 번 인계한다. 검수자는 같은 Direction에 별도의 Review
Task 실행계획을 저장하고 기존 SELF/MANAGER 흐름으로 검수·허가된 후속 작업·반환을 한다.
이 인계 자체는 병합/배포 권한이 아니며 현재 Work와 실제 사용자 승인 범위를 유지한다.

최종 완료에는 검수자의 정확 반환 출처, 원래 반환 Operation APPLIED, 해당 응답의
계획 revision/진행 N/N, `LOOP ACCEPTANCE: PASS` 및 같은 `LOOP CANDIDATE SHA: <SHA>`가
필요하다. 일반 CODE_REVIEW_PASS나 CI 성공만으로 완료하지 않는다. 전체 사용자 수락
범위가 미완료면 HOLD로 반환한다. 검수 중에는 원 Loop의 SELF·복구 실행을 멈추며,
역할 변경·원 Manager 교체·검수자 전송 UNKNOWN은 추정하여 재개하지 않는다.

`status`는 원 계획/최신 진행 관측과 검수 상태를 함께 반환한다. 검수 미결속인 기존
Loop의 동작은 유지한다. 현재 후보는 기존 Supervisor 재사용 경로이며 자동 생성과
검수 전송 후 Manager 승계는 별도 안전 절차가 필요하다. 전송 전 CONFIGURED 검수
결속만 검증된 Loop 후계 Epoch 이전과 같은 트랜잭션에서 새 owner로 이전한다.
옛 owner와 인계 영수증은 history에 남고, 전송 전 새 owner의 실제 Manager 역할과
Supervisor 전역 역할을 다시 확인한다. 이 결속 이전은 역할을 자동 변경하지 않는다.
실제 반환 APPLIED가 확인된 REVIEW_HOLD는 `resume_review`에 현재 owner/epoch와
정확 `review_response_sha`를 주어 명시적으로 재개한다. 이전 회차 전체를 history에
보존하고 새 Epoch·검수 Task·Operation ID로 수정→새 SHA→재검수한다. UNKNOWN이나
미반환 전송은 이 경로를 사용할 수 없다. 이전 DELIVERED SELF는 ACK를 가장하지 않고
RETIRED_FOR_REVIEW로 보존하여 재개 후 옛 응답을 다시 실행하지 않는다.
로컬 mock 테스트는 실제 RCC/운영 인계·독립 검수·배포 성공의 증거가 아니다.


### Loop 원 요청자 결과 보고와 노드 생성 제한

독립 Supervisor 수락과 원 요청자/사용자 보고는 별도 사실이다. 검수 완료 시 기존
`loop.state=COMPLETED` 의미는 유지하되, 같은 트랜잭션에서 정확 후보 SHA, 검수 응답
SHA, 원 반환 Operation과 검수 결과를 `result_report.result`에 저장한다.
`user_notification=UNVERIFIED`는 BCT가 dot의 사용자 메시지 전달을 증명하지 못한다는 뜻이다.

`requester_ref`는 원 요청의 명시적인 상관 참조이며 RCC UUID나 외부 채널 주소가 아니다.
`start` 또는 `configure_requester`에 이 참조만 주면 `REQUESTER_PULL` 모드이다.
수락 뒤 `READY_FOR_REQUESTER` 결과를 `bct_loop_recipe(status)`에서 읽고 원 요청자 dot이
사용자 보고를 맡는다. 경로를 모른다고 Manager·Supervisor·임의 UUID로 보내지 않는다.
미결속 기존 작업도 수락 결과를 이 상태로 보존하며, 미전송 결과에 원 요청자를 한 번 결속할 수 있다.

`requester_conversation_key`까지 명시한 경우에만 기존 RCC 대화에 선택적으로 보고한다.
결속 때 정확한 최신 UUID/attachment를 확인하고, 전송 직전 다시 최신·idle 상태를 확인한다.
Loop Manager나 검수 Supervisor로 자기 반환하지 않는다. 결속·결과·원 Operation은 불변이며
새 requester로 바꿔 재전송할 수 없다. `PENDING`에서 선예약 후 `DISPATCHING`으로 이동하고,
원 영수증의 정확 대상·본문 해시·Operation·instance가 APPLIED일 때만
`DELIVERED_TO_CONVERSATION`이다. 이는 사용자 통지나 읽음/ACK를 뜻하지 않는다.
없거나 불명확한 영수증은 `UNKNOWN`; 확정 미실행은 `NOT_APPLIED`로 보존하며 자동 재전송하지 않는다.

신규 공개 Loop 시작의 `allow_new_nodes` 기본값은 false이다. 같은 Manager의 SELF 복구는
계속 허용되지만 후계 노드 생성과 초기 메시지 선예약은 이 제한을 확인한다.
기존 실행의 미설정 정책은 역사적 동작을 보존한다. 현재 owner/epoch의 명시적인
`configure_recovery(allow_new_nodes=false)`로 기존 실행에도 금지를 기록할 수 있다.
Loop가 이미 소유한 Direction은 `pending_chain_starts`에 표시하지 않는다.
불확실한 영수증 안내는 단일 Manager에게 자기 자신으로 반환하라고 하지 않고 원 영수증
조정과 미해결 상태 보존, 결속된 요청자 보고 경로 사용을 안내한다.
