# Chain Message Recipe V2

## 한 문장

`Chain Message`는 사용자 요청을 A(Manager)가 **전체 방향과 전체 계획**으로
정리하고, B(Worker)가 그 경계 안에서 **구체적인 실행계획**을 작성·실행한 뒤,
BB 반복 또는 BA 반환으로 끝내는 전체 레시피다.

```text
사용자 → A 전체 계획 → 정확한 A→B 전달 → B 실행계획·실행 → BB 또는 BA → A 재판단
```

`bct_chain_message`는 이 레시피 안의 정확한 전송·응답 감시 부품이다. 그것만으로
전체 Chain Message가 완성되지는 않는다.

## 전체 맵

```text
사용자 요청
  ↓
A / Manager
  1. set_direction  : 사용자 방향 + 전체 계획 기록
  2. check_run      : 현재 현실 확인
  3. set_network    : 이번 A→B에 필요한 최소 망 준비
  4. check_ready    : Work·대상·영수증·UNKNOWN 최종 확인
  5. task_message   : 감시 선등록 후 정확히 한 번 전송
  ───────────── 실제 대화 턴과 판단 주체 변경 ─────────────
B / Worker
  6. plan_run       : B의 구체적인 실행계획과 자원 선택
  7. run_task       : 실행
      ├─ BB: 진전이 있고 다음 안전한 실행이 분명하면 B가 계속
      └─ BA: 완료·위험·정체·판단 필요면 A에게 결과 반환
  ↓
A / Manager
  8. return_result  : 결과·증거·미완료·위험을 읽고 판단
      ├─ COMPLETE: 필요하면 Supervisor 최종 검토 후 종료
      └─ NEW_TASK: 새 Chain Message를 1번부터 시작
```

## A와 B의 계획은 다르다

### A: `set_direction` — 전체 방향과 전체 계획

A는 사용자 요청을 다음 내용으로 정리한다.

- 최종 목표와 완료 기준
- 작업 범위·우선순위·금지사항
- 큰 작업 순서와 각 경계
- B에게 맡길 부분과 B의 재량 범위
- 위험·외부 변경·병합·배포 시 반환 또는 Supervisor 검토 조건
- B가 제출할 증거

A는 방향만 말하고 B에게 모든 판단을 넘기지 않는다. 반대로 파일명·명령 한 줄
단위까지 미리 고정해 B의 독립적 점검을 무력화하지도 않는다.

### B: `plan_run` — 구체적인 실행계획

B는 전달받은 A 방향과 실제 자기 환경을 읽은 뒤 다음을 결정한다.

- 실제 파일·모듈·부품·레시피
- 프로그램·PowerShell·데스크탑 기능
- 실행 순서와 단계별 완료 증거
- 관련 테스트·CI·배포·복구 방법
- 다음 BB가 허용되는 정확한 조건

B는 A의 목표·범위·금지사항·위험 경계를 변경할 수 없다. 바꿔야 하면 BA로
반환한다.

## 준비 구간

### 1. `set_direction`

현재 공개 저장 부품은 `bct_set_direction`이며, 호환 이름은
`bct_set_chain_direction`이다. 이 기록은 전송하지 않는다.

### 2. `check_run`

읽기 전용 현실 확인이다. `bct_status(scope="bct")`를 기본 입력으로 사용하고,
필요한 경우 프로젝트·Work·영수증·Git·CI·LIVE·대화망 정보를 함께 읽는다.
`bct_status`는 `check_run` 전체가 아니라 가장 기본적인 상태 부품이다.

### 3. `set_network`

기존 대화망과 역할이 맞으면 재사용한다. 부족할 때만 현재 A를 Manager로, 적합한
일반 노드를 B로, 전역 Supervisor를 준비한다. 미래 작업용 노드를 미리 만들지
않으며 역할 충돌은 임의로 덮어쓰지 않는다.

### 4. `check_ready`

전송 직전 정확한 B 대화 UUID·창·탭·Work 권한·기존 영수증·UNKNOWN을 대조한다.
현재 `bct_chain_message(action="preflight")`는 Work 권한과 전송 원문 계약을
검사하는 부분 부품이다. 물리적인 탭 상태까지 포함한 `check_ready` 전체 레시피는
별도 조립 대상으로 남아 있다.

### 5. `task_message`

새 Manager→Worker 작업의 기본 공개 명령이다. Task Message가 작업·완료 기준·BB/BA
규칙을 한 묶음으로 만들고, 내부에서 Chain Message가 감시를 먼저 준비한 후 정확한
대상에게 한 번 전송하고 영수증을 남긴다. UNKNOWN은 새 Operation으로 재전송하지
않는다.

`send_message`는 사람이 Manager에게 운영 지시를 주거나, 승인·복구처럼 Worker
작업이 아닌 직접 메시지가 필요한 예외에만 사용한다.

## BB와 BA

BB의 기본 종료 조건은 횟수가 아니라 **진전 없음**이다. 기본 `max_rounds=0`은
고정 한도 없이 계속한다는 뜻이며, 양수 한도는 사용자나 A가 비용·시간 예산으로
명시했을 때만 쓴다.

BA 반환에는 최소한 원래 목표, 실행 결과, 증거, 미완료 작업, 위험, 다음 선택지를
포함한다. A가 이를 읽은 뒤 `COMPLETE`, `NEW_TASK`, `ASK_USER`, `HOLD` 중 하나를
새 Direction으로 기록한다.

## 고정 안전 바닥

다음은 레시피에서 빼지 않는다.

- 정확한 대화 UUID와 Work·권한
- 전송 전 감시 등록
- 한 번 전송과 영수증
- UNKNOWN 재전송 금지
- 역할 충돌 보존
- 응답 감시와 복구 기록

그 위의 방향 정리, 대화망 준비, 도구 선택, 반복 정책, 테스트·CI·배포,
Supervisor 검토는 교체 가능한 부품이다.
