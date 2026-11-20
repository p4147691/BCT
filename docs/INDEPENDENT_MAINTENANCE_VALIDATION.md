# 독립 정비 완료 및 검증 기록

## 완료 판정 (2026-11-20)

사용자 요청 범위인 **BCT 없이 수정·검증·운영 적용·복구할 수 있는 정비 경로 분리**는
완료했다. 아래 초기 후보 기록의 "운영 미적용"은 당시 판정이며 현재 상태가 아니다.
구현 위치와 사용 순서는 [정비 안내](INDEPENDENT_MAINTENANCE.md)를 따른다.

| 단계 | 검증 결과 및 증거 |
|---|---|
| 최초 운영 전환 | Core `dc4cc9d5d9cff15d44c60b9616f03a0153881367`. 후보 CI `44543861111`, main CI `44545614691` 각각 14/14 통과. 외부 정지·백업·복구 기동, BCT import 차단 상태의 독립 supervisor 확인. 전후 DB 82개 테이블 동일. `D:/BCT/maintenance/operational-installation.json` |
| 이미 실행 중인 start 보완 | 독립 도구 `5ead8775987b10250a1a337af1065462bca28b15` 설치. 정상 실행은 읽기 전용 성공, 소유한 pause는 안전 확인 후 재개. `D:/BCT/maintenance/start-fix-5ead8775987b10250a1a337af1065462bca28b15.json` |
| DB 지문 경합 수정 | 소스 `ad240b3c1350bb428eefc2c47a4b5ab0b7d223b2`. 로컬 29개 통과. 후보 CI `44558920451`, main CI `44559922732` 각각 첫 시도 14/14 작업, Core 테스트 1,770개 통과. 초기화 지연을 강제해 실제 지문 변경·거부를 재현. 안전 검사 유지. `D:/BCT/maintenance/history/schema-ci-fix-ad240b3c1350bb428eefc2c47a4b5ab0b7d223b2.json` |
| Core 기동 불능 격리 시험 | 설치된 독립 묶음 사용, 정비 프로세스의 `bct` import 차단. 실제 Core 시작 시 예외 주입 → 기동 실패·UNKNOWN 기록 → 새 ID 우회 거부 → 꺼진 상태에서 외부 수정·컴파일·import 검증 → 보관판 복구·기동 → 수정판 적용·기동·접수 재개 모두 PASS |

격리 시험은 간단한 대체 서버가 아닌 실제 복제 Core를 사용했다. 임시 DB의 Work,
Operation, Claim 전체 행과 보존용 데이터를 비교해 유지됨을 확인했고, 최초 UNKNOWN
영수증도 삭제하지 않았다. 시험용 Core는 마지막에 정지했다. 운영 전후의 PID·세대·
정비 설정·작업 건수·미해결 Claim 내용·진행 중 소스 파일 지문은 동일했다.
이는 비교한 관측의 보존 증거이며 운영 DB 전체 바이트 비교를 주장하지 않는다.

격리 시험 산출물(로컬 보관, Git 비포함):

- 재현 스크립트: `D:/BCT/worktrees/core-maintenance-20261119/artifacts/dead_core_drill.py`
- 로그: 같은 artifacts의 `dead-core-drill.log`
- 단계별 결과·운영 비교: 같은 artifacts의 `dead-core-drill-lh3npjup/report.json`
- 임시 정비 영수증·백업: 같은 시험 폴더의 `runtime/maintenance`

위 시험 릴리스 SHA들은 임시 저장소의 고장판·복구판·수정판이며 운영 배포판이 아니다.
문서 정리 시점에는 소스/문서만 반영하며 Core·독립 묶음 재설치가 필요 없다.
실제 설치 버전은 항상 `D:/BCT/maintenance/operational-entry.json`에서 다시 확인한다.

## start 및 접수 재개 운영 검증 (2026-11-20, KST)

수정은 `operator.py::start`에서 정상 실행·소유한 정비 일시중지·정지를 구분한다.
정상 실행이면 pause 없이 반환하고, 실행 중인 정비 일시중지 상태에서는 기존 resume
검사를 사용한다. 릴리스 신원·표식 소유권·UNKNOWN 검사는 유지한다.
설치된 독립 도구는 `5ead8775987b10250a1a337af1065462bca28b15`, 운영 Core는
`dc4cc9d5d9cff15d44c60b9616f03a0153881367`이다. 이번 검증 중 재기동은 없었다.

- 해당 도구 SHA의 후보 CI `44551520940`과 main CI `44552733341`은 각각 14개
  작업 성공을 조회했다. main CI의 최초 실패와 재실행, 후속 테스트 경합 수정은 아래
  DB 스키마 지문 절에 구분해 보존한다. 이 문서 변경에 대한 CI 결과는 아니다.
- 정상 실행 상태에서 실제 `maintenance.cmd start` 성공. PID 4524·세대 470 유지,
  두 정비 표식 없음, Core health의 `maintenance_paused=false` 확인.
- 외부 도구로 pause한 뒤 Core health의 `maintenance_paused=true`를 확인하고
  실제 `maintenance.cmd start` 호출. 재기동 없이 `false`로 전환하고 두 표식을 제거했다.
  기존 정비 영수증은 동일하며 이번 pause·resume의 COMPLETED 영수증만 추가됐다.
- 접수 재개 후 실제 MCP로 읽기 전용 Work를 새로 만들고 `bct_read`로 정비 README를
  한 번 읽었다. 새 Operation은 `FINISHED / APPLIED`, `duplicate=false`, `error=null`이며
  영수증을 재조회하고 반환 파일 해시를 로컬 파일과 대조했다. APPLIED는 이 읽기 요청의
  성공 결과이며 파일 수정이나 메시지 전송을 뜻하지 않는다.
- 접수 시험 전후 기존 Work·Operation·Claim·background_jobs의 모든 행 해시가 보존됐다.
  Work 2,320→2,321, Operation 33,898→33,899, Claim 5,668 유지,
  background_jobs 830 유지. 새 Claim·백그라운드 작업은 없다.
  테스트 Work는 read 권한만 가진 ACTIVE 범위로 남기며 자동 실행을 의미하지 않는다.
  완료된 테스트 Operation과 기존 UNKNOWN/Claim을 삭제하거나 상태 변경하지 않았다.

운영 증거는 다음 로컬 파일에 보관한다. JSON 시각은 UTC이며 위 날짜는 KST이다.

- 정상 실행 start: `D:/BCT/maintenance/start-verification-20261120-current-chat.json`
- pause 후 start: `D:/BCT/maintenance/paused-start-verification-55d3d1ad0244424687c209af08790bfa.json`
- 접수 전 행 해시: `D:/BCT/maintenance/admission-read-test-20261120-before.json`
- 새 접수·완료·보존 비교: `D:/BCT/maintenance/admission-read-test-20261120-result.json`
- Work: `maintenance-admission-read-20261120-01a1f450`
- Operation: `maintenance-admission-read-20261120-01a1f450-op1`

별도 격리 폴더 `D:/BCT/worktrees/maintenance-start-20261120`에는 정지+pause에서
start 후 재개하는 회귀 테스트 추가분을 보존했다. 기준 `5ead877`과 해당 미커밋 추가분에서
독립 정비 24개·접수 5개 테스트, compileall, diff 검사를 통과했다.
이 추가분은 당시 운영 묶음이나 위 CI에 포함되지 않았다.
후속 정본 반영(2026-11-20): 같은 테스트를
`tests/test_independent_maintenance.py::IndependentMaintenanceTests.test_operator_start_stopped_paused_starts_and_resumes`
에 편입한다. 원래 격리 폴더의 변경과 운영 검증 기록은 보존한다.
이 반영은 테스트와 문서만 변경하며 운영 묶음·Core에는 적용하지 않는다.

이번 운영 확인은 실행 중인 Core의 start 및 읽기 요청 한 건의 실제 접수·완료 범위다.
정지+pause의 start는 위 격리 증거와 구분한다. 쓰기·외부 메시지·브라우저 조작·장시간 작업,
동시 접수 경쟁·부하·장애 중 재개는 이번 운영 시험 대상이 아니다.
보존 비교는 명시한 네 테이블과 관측한 영수증·서비스 파일 범위이며 DB 전체 바이트 검증은 아니다.

## 남은 한계

- DB 자체 손상 복원, 과거 DB 덮어쓰기, 스키마·데이터 마이그레이션은 자동 처리 범위가
  아니다. 코드 복구는 현재 작업 기록을 보존한다.
- `current.json` 자체가 해석 불가능한 경우와 승인된 복구판·정책·지문이 없는 경우에는
  별도 진단이 필요하다. UNKNOWN 효과를 추측해 재전송하거나 Claim을 지우지 않는다.
- Python·psutil·파일/프로세스 권한은 필요하다. BCT Core에는 의존하지 않는다.
- Chrome/RCC/Monitor, 운영 브라우저 고장, 디스크·OS 장애의 복구까지 입증한 것은 아니다.
- 기동 불능 시험은 시작 시 코드 예외 한 종류를 주입했다. 모든 장애 조합의 보장은 아니다.
- 기존 테스트는 CI에 포함되지만 이번 전체 기동 불능 시나리오는 로컬 격리 수동 검증이다.

이번 완료 범위에 남은 필수 작업은 없다. 위 한계는 별도 요청이 필요한 범위다.

## 초기 후보 기록 (역사)

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
