# Core V1 설계 검토 및 acceptance matrix

상태: DESIGN_REVIEW_COMPLETE / FIRST_SLICE_RELEVANT_CASES_TESTED.
아래 전체 표는 설계 판정이며, 첫 files/git/tests 범위에 해당하는 실행 증거는 `exec-plans/completed/BCT_FOUNDATION.md`에 기록한다.
검토자: 현재 Codex 작업. 별도 독립 리뷰 또는 서브에이전트 리뷰를 수행했다고 주장하지 않는다.

## 결합/실패 시나리오 검토

| ID | 시나리오 | 설계에서 요구한 결과 |
| --- | --- | --- |
| I01 | node 이름 변경 | work, principal, operation_id와 연결 유지 |
| I02 | role/group 변경 | 새 라우팅에만 반영; 기술 권한 변화 없음 |
| I03 | node 없이 인증된 로컬 요청 | 사용자 scope 내 일반 작업 가능 |
| I04 | 같은 node_id를 외부 요청이 주장 | 인증 principal 증거 없으면 거부 |
| I05 | tab/window 또는 conversation 변경 | 확인된 endpoint 교체와 generation 증가; 자동 권한 승격 없음 |
| I06 | 교체 전 연결의 늦은 응답 | 원 operation의 증거로 기록, 새 endpoint 응답으로 사용 금지 |
| I07 | owner 이름 변경 뒤 같은 파일 재편집 | work/epoch/post-hash 기준으로 정상 진행 |
| I08 | 실행자가 사라졌고 NOT_APPLIED 증거 확인 | 실행 부재 확인 후 기록 보존 인계 |
| I09 | lease 만료지만 프로세스 살아 있음 | 자동 takeover 금지 |
| I10 | 프로세스 없음, 과거 효과 UNKNOWN | 해당 대상의 중복 효과 금지; unrelated 작업은 허용 |
| P01 | 미등록 사용자 프로젝트의 요청 범위 내 편집 | 등록 여부 단독 차단 없음; target/권한 검증 |
| P02 | 허용된 read로 process/deploy 호출 | 별도 action과 요청 scope 판단; read 허용 전용으로 권한 확대 불가 |
| P03 | 정책 승인 후 파일/HEAD 변경 | 실행 직전 precondition 검사로 거부 |
| P04 | 정책 승인 후 principal/scope/revision 변경 | dispatch 전 재평가 |
| P05 | role을 MANAGER로 변경 | 기술 권한 자동 증가 없음 |
| P06 | 대규모 삭제/인증 변경 | exact 요청과 승인 근거가 있을 때만 실행 |
| P07 | symlink/junction으로 scope 이탈 | canonical target 검증에서 거부 |
| P08 | 같은 승인으로 다른 내용/대상 실행 | digest/scope 불일치로 재평가 |
| P09 | 설정 파일 불완전/파손 | 구체적인 설정 오류, mutation 차단 |
| O01 | 같은 operation_id/같은 입력 두 번 호출 | 결과/상태 반환; 두 번째 executor 호출 없음 |
| O02 | 같은 operation_id/다른 입력 | ID conflict 거부 |
| O03 | intent 기록 후 executor 진입 전 실패 | 실행 부재 증거가 있을 때 NOT_APPLIED |
| O04 | UI submit 후 결과 저장 전 crash | inspect_outcome; 증거 부족이면 UNKNOWN, resend 금지 |
| O05 | 이전 응답을 신뢰할 수 없는 상태에서 새 작업 | 먼저 관측 오류와 실제 외부 동작을 구분; 단순 측정 실패는 Claim 없이 무시하고 정상 진단·수리 진행. 위험한 동일 외부 변경만 정확한 대상/승인/실행 증거로 보호 |
| O06 | 실행 전 거부 후 정상적인 수정 재시도 | 연결된 새 operation, 새 precondition으로 진행 |
| O07 | 두 작업이 같은 파일/repo index 변경 | 원자적 claim 충돌 검출 |
| O08 | 서로 다른 worktree 작업 | 실제 공유 자원 충돌이 없으면 병렬 가능 |
| O09 | 정상 작업의 여러 차례 수정 | 확인된 post-hash 갱신으로 허용 |
| O10 | ACT와 BCT가 동일 LIVE 변경 | 공유 조정 확인 또는 bounded 단일 writer 전환 전 실행 금지 |
| O11 | 다른 principal이 operation ID를 알아내 결과 재조회 | work/result 조회 권한 확인 전 결과 공개 금지 |
| O12 | 실패는 확인됐지만 rollback 실패/부분 효과가 남음 | FINISHED/FAILED만으로 claim 해제나 재시도 허용 금지 |
| M01 | source만 BCT로 이동 | MCP/extension identity는 별도 보존; 실제 계약 테스트 필요 |
| M02 | feature catalogue에 실행기 없는 도구 | 등록/계약 검사에서 실패 |
| M03 | 기존 role binding/UNKNOWN RCC send 존재 | 현재 기록 보존, 기능 이전을 이유로 재실행 금지 |

## 검토에서 보완한 사항

1. node identity와 authenticated principal을 분리하여 이름·role 변경이 권한 변경으로 번지지 않게 했다.
2. 설정 한 파일에 operation/동적 연결까지 몰아넣는 대신 단일 관리 entrypoint와 SQLite 상태를 구분했다.
3. *초기 설계 기록:* UNKNOWN 뒤 새 ID의 중복 실행을 Claim으로 다뤘으나, 현재는 관측 실패를 먼저 분리하고 관측 결과만으로 Claim/작업 중단을 허용하지 않는다. 외부 변경의 실제 중복 보호는 별도로 판단한다.
4. 임대 만료/프로세스 부재만으로 안전한 인계를 인정하지 않고 terminal/effect evidence를 함께 요구했다.
5. 외부 효과의 exactly-once를 보장한다고 쓰지 않고 crash gap과 증거 부재를 명시했다.
6. BCT 내부 lock만으로 ACT의 기존 writer를 제어할 수 없다는 전환 경계를 명시했다.
7. 기존 전체 gateway의 영구 wrapper가 아닌 BCT 소스 소유 방향을 반영했다.
8. 정책 변경 후 오래된 허용 결과, 동시 설정 변경, stale 연결 응답을 다뤘다.

## 구현 시 실제로 확인할 것

- SQLite transaction/unique constraint/CAS가 병렬 호출에서 한 executor 진입을 보장하는가.
- 외부 호출 전후 crash 주입 시 UNKNOWN과 결과 복원이 정확한가.
- 오래된 기록이 unrelated 새 작업을 막지 않는가.
- 이름·그룹·연결 변경에 따라 task 또는 권한을 재설정할 필요가 없는가.
- 요청 scope를 확인된 사용자 지시에서 얻고 caller가 임의 작성한 승인 주장으로 대체하지 않는가.
- 파일/Git/테스트의 대상/프로세스 evidence가 직접 호출과 MCP 호출에 일관적인가.

이 검토는 실행 증거를 대신하지 않는다. 후속 구현에서 위 ID를 실제 테스트/acceptance에 연결한다.

## 설계 요구사항과 검증 증거 연결 (2026-10-13)

아래 표는 대표적인 **직접 확인된** 테스트 연결이다. 하나의 테스트가 여러 조건을 검증할 수 있지만, 모든 matrix ID가 개별 테스트로 검증됐다는 뜻은 아니다. 설계 검토와 최초 acceptance는 별도 문서로 유지한다.

| 설계 ID | 대응 테스트 / 증거 | 범위 |
| --- | --- | --- |
| I01, I02, I05 | `tests/test_core.py::CoreTests.test_node_properties_and_connection_are_independent_of_work` | 노드 이름·역할·그룹·연결 변경과 work 분리 |
| O01 | `tests/test_core.py::CoreTests.test_duplicate_operation_executes_once` | 동일 작업 중복 실행 방지 |
| O02 | `tests/test_core.py::CoreTests.test_same_operation_id_with_different_request_is_denied` | ID 충돌 거부 |
| O05 | `tests/test_core.py::CoreTests.test_finished_unknown_does_not_block_next_operation` | 이전 측정 UNKNOWN이 새로운 작업을 가로막지 않음 |
| O07 | `tests/test_core.py::CoreTests.test_concurrent_writer_for_same_resource_is_denied` | 동시 writer 충돌 |
| O11 | `tests/test_core.py::CoreTests.test_wrong_principal_cannot_run_or_read_result` | 타 principal 결과 접근 차단 |
| P03 | `tests/test_development_flow.py::DevelopmentFlowTests.test_stale_file_hash_is_not_written`; `test_stale_head_is_not_committed` | 오래된 파일 SHA / HEAD 거부 |
| P07 | `tests/test_development_flow.py::DevelopmentFlowTests.test_symlink_escape_is_denied_when_platform_allows_creation` | 허용 root 밖 symlink 접근 차단 |
| M02 | `tests/test_mcp_integration.py::MCPIntegrationTests.test_authenticated_catalogue_work_call_and_duplicate_receipt` | MCP 카탈로그와 등록 executor 일치 |
| O04, M03 (부분) | `tests/test_rcc_integration.py::RCCIntegrationTests.test_ambiguous_effect_is_not_retried` | 불확실한 RCC 효과 재전송 방지 |

기타 ID는 별도 후속 모듈 테스트, acceptance 또는 추가 검증과의 매핑이 필요하다. **이 표에 없는 ID를 PASS로 간주하지 않는다.** 첫 구현 당시의 검증 기록은 [BCT_FOUNDATION.md](exec-plans/completed/BCT_FOUNDATION.md)를 참고한다.
