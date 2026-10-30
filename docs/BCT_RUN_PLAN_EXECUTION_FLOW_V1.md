# BCT 영속 실행 구조 V1 — 계획 우선 (2026-10-31)

## 원칙
- **PR #381의 bct_task_run / bct_chain_run은 아직 준비된 세션을 전제로 한 실행 명령이다.** 먼저 전체 호출 구조를 고정하고, 사전 준비가 자동으로 포함됐다고 주장하지 않는다.
- 사용자용 최초 명령 이름은 **run-plan**으로 정한다. **현재 새 공개 MCP 명령이 아니다.** 기존 `project-run-plan`은 프로젝트 실행 기본 기록을 만들 뿐 2~6단계 상세 Chain 계획을 자동으로 짜는 기능은 아니다.
- 기존 오케스트레이션 엔진, node-sync, WorkerResultInbox, RCC, 메시지 명령은 보존한다.

## 실행 순서
```text
run-plan (독립 공개 후보; 미구현)
  목표/완료조건/단계(예: 0/3)/담당자/프로젝트 ID/계획 ID
      ↓
status node + status rcc (기존 공개 조회)
  실제 노드·대화 UUID·RCC 세션/탭 확인; 단순 답변 조회와 다름
      ↓
session-start (기존 orchestrate 내부 실행)
  목표·acceptance·허용 범위와 실행 session ID를 BCT에 영속 저장
      ↓
node-sync (기존 orchestrate 내부 지원)
  실제 RCC 노드/대화 연결을 확인하고 session attachment를 영속 기록
      ↓
project-run-bind (프로젝트 실행 등록을 쓰는 경우에만)
  run ID·session ID·매니저 attachment/세대를 기록·검증
      ↓
task-run (PR #381 공개 후보; dispatch 엔진)
  단일 assignment 지시/완료조건/대상/결과·영수증
      ↓
chain-run (PR #381 공개 후보; 2~6개 task + synthesis)
  내부에서 기존 dispatch를 단계별로 재사용, 결과를 종합
      ↓
status (기존 orchestrate 상태 조회; read-only)
  단계 진행·결과 확인
      ↓
chain-resume (기존 orchestrate 내부 복구; 필요할 때만)
  original_operation_id로 기존 plan/assignment 결과를 복원하고 안전한 잔여 단계 재개
```

## 독립화 경계
- run-plan은 계획을 생성·검증·저장하는 역할이다. 계획서 파일을 별도로 강제할 필요는 없지만 작업 단계·완료조건은 명시해야 한다.
- status 조회는 실행이나 저장을 하지 않는다.
- session-start와 node-sync는 단순 조회가 아니라 DB 실행 기록/attachment 연결을 생성한다. RCC 실제 대상과 권한을 임의로 추정하지 않는다.
- project-run-bind는 프로젝트 관리 레이어용이며 모든 단순 chain-run에 필수라고 가정하지 않는다.
- task-run은 메시지 전달에 작업 배정·acceptance·영속 결과를 더한 실행 기능이다.
- chain-run은 task-run을 순차 재사용하나 마지막 synthesis가 추가된다. 기존 구현은 2~6 작업을 요구한다.
- chain-resume은 상태 조회와 다르며, 원본 기록 확인 후 재개 가능한 작업에 실행 효과를 줄 수 있다.
- AA 동일 노드 반복, 단계별 ChatGPT 자율 판단, AB/BB/BA는 별도 격리 E2E가 필요하다. 구현됐다고 가정하지 않는다.

## 단계적 수락
1. run-plan 명세/실제 기존 project-run-plan과의 차이 검증.
2. session-start / node-sync의 입력·출력·DB 영속성 격리 시험.
3. PR #381 task-run 단일 작업 실행과 chain-run 동등성·기존 영수증 회귀.
4. read-only 상태 조회와 chain-resume의 실행 효과 분리 시험.
5. AA 반복 후 AB→BB→BA 확대.
6. 검증된 변경만 main/LIVE 배포. 기존 사용자 탭·운영 DB 직접 편집 금지.
