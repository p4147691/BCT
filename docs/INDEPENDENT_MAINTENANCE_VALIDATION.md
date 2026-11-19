# 독립 정비 후보 검증 기록

기준 main: `8707fb1184592809234b6968be51cff5632e1122`

작업공간: `D:\BCT\worktrees\core-maintenance-20261119`

브랜치: `feat/core-maintenance-20261119`

판정 범위: 격리 구현 및 로컬 검증. 운영 설치·서비스 변경·GitHub 게시·CI 실행 없음.

## 확인한 결과

| 검증 | 결과 | 증명의 범위 |
|---|---|---|
| 독립 정비 테스트 | 13개 통과 | 깨진 BCT import와 독립 실행, 실제 테스트 프로세스 기동·종료·복구, 정확한 무응답 프로세스 종료, 승인된 main 배포, 변조·중복·UNKNOWN·활성 작업 거부, DB 사본, 분리한 묶음 |
| 기존 배포 회귀 테스트 | 15개 통과 | 기존 BCT 기능 경로의 실제 격리 배포·재기동·rollback·영수증 처리. 실행 약 451초 |
| 실제 Core 외부 정비 시험 | 1개 통과 | 임시 디렉터리와 포트의 실제 BCT Core를 외부 도구로 정지·기동. Work ID 목록 보존. 실행 약 35초 |
| 공통 잠금 변경 후 서비스 경로 재확인 | 1개 통과 | 기존 배포·중복·restart·stop·start 시험 재실행. 실행 약 67초 |
| 기존 Core Operation 테스트 | 20개 통과 | 기존 중복·UNKNOWN·소유권·백그라운드 실행 계약 |
| 기존 MCP 통합 시험 | 1개 통과 | 실제 격리 HTTP/MCP와 인증·호출·중복 영수증 |
| 나머지 회귀 테스트 | 1,700개 실행: 최초 1,693 통과, 실패 7건 후속 해결 | 최초 결과는 약 690초. 실패 원인과 재검증을 아래에 구분 |
| 컴파일·diff 검사·기능 목록 일치 | 통과 | Python 구문, Git whitespace, 생성된 기능 목록의 소스 일치 |

검증 범위는 중복 재실행을 제외하고 **1,750개 테스트 항목**이다. 처음부터 한 번에
모두 성공한 것은 아니다. 1,700개 묶음의 최초 실패 기록을 보존했다.

- 보호된 배포 2건: 옮긴 함수의 이전 namespace에 mock을 연결한 테스트를 실제 구현
  소유 위치에 맞게 수정했다. 보호된 전환 조건 자체는 완화하지 않았다.
- supervisor 4건: 기존 import namespace 호환성이 빠진 문제를 고쳤다. 기존 모듈을
  독립 구현의 alias로 제공해 같은 구현과 patch 지점을 공유한다.
- project-memory 1건: stdin으로 시작한 전체 테스트 harness에서 Windows spawn이
  `<stdin>` 경로를 실행하려다 OSError 22로 종료했다. 별도 재현 로그로 확인했고,
  `python -m unittest` 실행에서는 통과했다. 해당 기능의 제품 코드는 수정하지 않았다.
- 보호된 배포·project-memory 두 모듈 43개 재검증 통과, supervisor 4개 재검증 통과.
- 마지막 집중 재검증 27개 통과(약 10초). 결과는 `artifacts/final-focused.log`에 보관한다.

운영 상태 읽기 전용 확인은 독립 묶음의 `run.py status`로 수행했다. 운영 코드 import와
BCT 작업 호출 없이 기존 PID `8948`, 릴리스 `8707fb1...`, 미완료 Operation 1건과
미해결 Claim 37건이 관측됐다. 해당 건수는 각각의 작업이 지금 실행 중이라는 뜻이 아니다.
설정의 쓰기 기능은 비활성화했다. 운영 pause 파일·설정·DB·서비스를 변경하지 않았다.

## 산출물

- 기능·사용·거부 조건: `docs/INDEPENDENT_MAINTENANCE.md`
- 독립 명령행 구현: `src/bct_maintenance/cli.py`
- 공통 배포/복구 부품: `src/bct_maintenance/engine.py`, `releases.py`, `service_runtime.py`
- 격리 시험: `tests/test_independent_maintenance.py`
- 실제 Core 시험: `tests/test_deployment_service.py::test_external_maintenance_controls_real_isolated_core`
- 별도 보관 묶음: `artifacts/maintenance-candidate-final/run.py` 및 `bundle.json`
- 운영 읽기 전용 관측: `artifacts/live-readonly-observation.json`

artifacts는 Git에서 제외된 로컬 검증 산출물이며 운영 설치 위치가 아니다.

## 운영 전환 판정

현재 상태를 운영 적용 완료나 LIVE 복구 입증으로 해석하면 안 된다. Core/배포 메커니즘
변경이므로 정확한 후보 CI와 통합 검증이 필요하다. 사용자가 결과를 검토하기 전에는
운영 전환하지 않는다. 기존 운영판의 접수 중지 계약 부재, 미완료 작업·미해결 효과의
개별 확인, 복사 DB 기반 호환성 검증, 독립 묶음 설치 위치·권한·감시 경로가 후속 적용
계획의 필수 항목이다. 이 후보는 해당 조건을 대신 승인하거나 자동 정리하지 않는다.

## 최초 전환 보완 (2026-11-19 후속)

이전 운영 미적용 판정 이후 사용자가 운영 전환까지 승인했다. 이번 보완은 역사 기록을
삭제하는 대신 검토한 기록 지문과 OS 부팅 이전 동기 실행 증거를 사용한다. 구형 Core의
정상 종료 중에는 rollback-only SQLite 쓰기 잠금을 유지한다. 새 Core의 시작 시 복구와
알림도 정비 pause를 존중한다. 동일 main의 연결 작업폴더로 진행 중 파일을 보존하며
배포할 수 있고, 외부 operator 진입점과 별도 supervisor launcher를 제공한다.

검증 항목: 구형 health 계약 없이 정확한 프로세스만 종료·백업, 현재 부팅 이후 실행과
활성 전송 차단, 보존 지문 변화 차단, 두 번째 DB writer 차단·rollback, 기존 UNKNOWN
보존, 외부 stop/start/recover, main의 미추적 파일 보존 배포, pause/resume 소유권과 건강성.
정확한 최종 CI SHA와 운영 영수증·복사 DB 시험은 설치 보고서에 별도로 기록한다.

## DB 스키마 지문 CI 경합 수정 (2026-11-20)

main CI `44552733341`의 첫 시도에서 실제 격리 Core 외부 정비 시험이
`MAINTENANCE_DB_COMPATIBILITY_NOT_VERIFIED`로 실패했다. 같은 SHA 재실행 통과는
수정 증거가 아니다. 최초 로그에는 당시 테이블별 차이가 없어 그 실행의 누락 테이블을
특정할 수는 없지만, 다음 실행 순서로 같은 지문 불일치와 거부를 확정적으로 재현했다.

1. 임시 복제 릴리스에서만 Loop 생성자 직전에 파일 장벽을 삽입한다.
2. 실제 HTTP `ready=true` 응답을 받되 Loop 초기화는 아직 진행하지 못하게 유지한다.
3. 이때 DB 지문을 저장한 뒤 장벽을 해제한다. 테이블·인덱스 23개가 추가되고 지문이
   바뀐다. 조기에 저장한 지문은 기존 호환성 검사에서 여전히 거부되어야 한다.
4. 초기화가 완료된 지문으로 외부 정지·기동을 수행한다. 각 단계의 스키마와 Work ID
   목록이 유지되어야 한다.

원인은 테스트가 HTTP 준비 완료를 비동기 DB 초기화 완료로 취급한 것이다.
`tests/test_deployment_service.py`의 `wait_for_loop_schema`는 빈 격리 런타임의 첫
성공한 Loop 주기(`loop_recipe_recovery.runs > 0`, `last_error=None`)를 기다린다.
이 신호는 해당 영속 테이블 생성자들이 완료된 이후 기록된다. HTTP 준비만으로는
통과하지 않고, 제한 시간 초과·Core 종료·Loop 오류는 명시적으로 실패한다.
고정 sleep, 지문 재시도, 임의의 새 지문 허용으로 실패를 숨기지 않는다.

이 장벽은 작업이 없는 테스트 픽스처에 한정된다. 운영 DB가 향후에도 변하지 않는다는
계약이나 기존 작업을 실행해도 된다는 허가가 아니다. 운영의 DB 호환성·UNKNOWN·Claim
검사와 기동 코드는 변경하지 않았다. 이 변경의 적용 대상은 테스트이며 운영 Core나
독립 정비 묶음 재설치·재기동은 필요 없다.
