# 독립 실행 명령 V1 — task-run / chain-run

기존 Core Gen255의 `bct_orchestrate` 하위 실행 기능을 **중복 엔진 없이** 별도 MCP 공개 도구로 노출한다.

| 공개 명령 | 기존 엔진 | 설명 |
|---|---|---|
| `bct_task_run` | `orchestrate(operation=dispatch)` | 세션 안의 작업자 배정 하나 실행 |
| `bct_chain_run` | `orchestrate(operation=chain-run)` | 2~6개 작업자 배정과 최종 synthesis 실행 |

공통 호출: `work_id`, `operation_id`, `arguments`, 선택 `approval_ref`.
- task-run의 arguments: `session_id`, `manager_epoch`, `assignment_id`, `worker_node_id`, `attachment_id`, `instruction`, `acceptance` 및 기존 선택 인자.
- chain-run의 arguments: `session_id`, `manager_epoch`, `tasks`, `synthesis` 및 기존 선택 인자.
- 입력에 `operation`을 지정했다면 해당 공개 명령의 실제 실행과 일치해야 한다. 다른 실행 명령을 우회할 수 없다.
- **사전 조건**: 기존 `session-start`, `node-sync`, 매니저 epoch 및 attachment가 준비돼 있어야 한다. 이 명령들은 자동 생성·동기화하지 않는다.
- **영속 기록**: 기존 Work/Operation/Session/Assignment/Result 영수증 및 `chain-resume` 경로를 그대로 사용한다.
- **검증 경계**: 신규 진입점의 도구 목록·기존 MCP 통합 테스트. AA 자기대화, 실제 작업자 응답, 새 공개 resume은 별도 E2E 필요.
- **보존**: `bct_orchestrate`, `node-sync`, `WorkerResultInbox`, `WorkerResultRecovery`, `DeliveryContinuationRecovery`, `send-message`, 운영 DB/Chrome/RCC/Monitor.
