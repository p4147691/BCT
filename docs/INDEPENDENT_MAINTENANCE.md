# BCT 없이 수정·검증·배포·복구하기

**완료 (2026-11-20):** 외부 수정·검증·운영 적용·보관판 복구 경로를 구현하고 운영에
설치했다. 실제 Core가 시작 단계에서 실패하는 격리 환경에서도 외부 수정 → 검증 →
보관판 복구 → 수정판 적용·기동·접수 재개를 확인했다. 결과와 남은 한계는
[검증 기록](INDEPENDENT_MAINTENANCE_VALIDATION.md)의 첫 부분을 읽는다.

새 대화에서는 정본 `AGENTS.md` 5B를 읽고 이 경로를 기본으로 따른다. 사용자는
"BCT를 수정해줘"라고 요청하면 되며, "BCT 없이"를 반복하거나 직접 명령을 실행할
필요가 없다. 현재 상태 확인 → 격리 수정·시험 → 필요한 정확한 후보 CI → 정본 main
통합 → 승인된 범위의 외부 운영 적용·기동 확인·접수 재개 → 원격 게시·CI 확인 →
결과 설명 순서로 진행한다. 운영 적용이 필요 없는 변경은 해당 단계를 생략한다.
검토만 요청한 범위는 유지하고, 이미 받은 해당 작업의 적용 승인은 반복해서 묻지 않는다.

BCT 본체와 정비 도구는 별도로 보관한다. 정비 도구는 `bct`를 import하지 않는다.
소스 문서와 실제 설치·운영 검증 결과는 별개이며, 실행 영수증은 runtime/maintenance에 남는다.

## 어디에 무엇이 있는가

| 위치 | 역할 |
|---|---|
| D:/BCT/source | 정본 main 소스 |
| D:/BCT/worktrees | 기존 작업을 보존하며 구현·검증하는 격리 공간 |
| D:/BCT/maintenance | Core 밖의 정비 도구·고정 설정·사용 안내 |
| D:/BCT/runtime/releases | 해시로 검증하는 운영판·복구판 |
| D:/BCT/runtime/maintenance | 정비 영수증과 SQLite 백업 |
| src/bct_maintenance/cli.py | 정비 명령, 승인 설정, 동일 요청 재실행 방지 |
| src/bct_maintenance/admission.py | 실제 실행과 보존할 과거 기록 구분, 최초 전환 쓰기 잠금 |
| src/bct_maintenance/engine.py, releases.py | 기존 BCT도 공유하는 배포·해시·복구 부품 |
| src/bct_maintenance/service_runtime.py | 정확한 PID·생성 시각·실행 파일을 확인한 Core 제어 |
| src/bct_maintenance/locking.py, supervisor.py | 동시 정비 방지, 독립 재기동 부품 |
| scripts/build_maintenance_bundle.py | Core 밖에 보관할 해시 검증 묶음 생성 |

기존 BCT import 경로는 호환 연결로 남는다. Chrome/RCC/Monitor는 이번 정비 대상이 아니다.

## 사용 흐름

조회 → 접수 일시중지(pause) → Core 정지(stop) → 백업/배포/복구 → 기동 확인 → 접수 재개(resume).
설치된 간편 명령은 D:/BCT/maintenance/README.md에 실제 경로와 함께 안내한다.

| 명령 | 하는 일 |
|---|---|
| status | Core·포인터·DB 상태 조회. 불확실한 관측은 UNVERIFIED |
| verify --target SHA | 보관 코드 해시와 승인된 DB 스키마 확인 |
| pause / resume | 이 도구가 소유한 접수·supervisor 정비 표식 설정/해제 |
| stop | 접수중지 응답 확인 후 정확한 Core를 정상 종료하고 DB 백업 |
| bootstrap-stop | 최초 전환 전용. 고정한 구형 릴리스·프로세스 신원과 DB 쓰기 잠금 필요 |
| start | 승인된 현재 릴리스를 기동 |
| backup | Core writer가 없을 때 SQLite backup API로 일관된 사본 생성 |
| activate --target SHA | 검증한 정본 main을 배포. --source-worktree로 같은 main의 깨끗한 연결 작업폴더 사용 가능 |
| recover --target SHA | 검증한 보관 릴리스로 코드 포인터 복구 후 기동. DB는 되돌리지 않음 |
| reconcile --operation-id ID | 원본 정비 기록과 현재 관측 대조. 재실행하지 않음 |
| stop-unresponsive | 명시한 fingerprint와 일치하는 무응답 Core만 종료. 다른 프로세스·트리 종료 없음 |

원시 CLI에는 --config, 쓰기에는 --operation-id와 --expected-current가 필요하다.
완료한 동일 요청은 영수증만 반환한다. STARTED/UNKNOWN을 새 ID로 우회할 수 없다.
정지 상태가 확인된 후 recover --resolves 기존ID로 원본과 연결한 복구만 가능하다.

## 간편 start의 상태별 동작

`maintenance.cmd start`는 현재 포인터·승인된 릴리스·실제 프로세스/health 신원이 모두
일치하고 이미 정상 실행 중이면 **pause, 재기동, 백업, 영수증 추가 없이** 성공한다.
진행 중인 BCT 작업도 그대로 둔다. 두 정비 표식이 이 도구 소유로 존재하면 기존 resume
검사를 거쳐 접수만 재개한다. 실제로 정지되어 있을 때만 pause → start → resume을 수행한다.
표식이 하나만 있거나 다른 소유자 것인 경우, 신원이 불확실한 경우, 정비 UNKNOWN이 남은
경우는 표식을 건드리지 않고 거부한다. 원시 CLI의 start는 정지 상태 전제 계약을 유지한다.
구현은 `src/bct_maintenance/operator.py::start`, 공통 미확정 정비 기록 검사는
`src/bct_maintenance/cli.py::Maintenance.check_pending_effects`를 사용한다.

2026-11-20 운영에서 정상 실행 start, pause 후 start의 접수 재개, 재개 후 새 읽기 전용
Work/Operation의 실제 접수·완료를 확인했다. 재기동 없이 기존 작업·기록을 보존했으며
테스트 기록도 남겼다. 정확한 증거·비교 범위·미검증 항목은
[운영 검증 기록](INDEPENDENT_MAINTENANCE_VALIDATION.md#start-및-접수-재개-운영-검증-2026-11-20-kst)을 따른다.

## 최초 전환에서 보존하는 것

구형 Core는 pause 계약을 모르므로 파일만 만든 것으로 안전을 주장하지 않는다.
bootstrap-stop은 SQLite BEGIN IMMEDIATE 잠금을 잡아 기존 Store의 새 작업·전송 예약
쓰기를 막는다. 잠금 안에서 실행 상태와 정확한 Core 신원을 재확인하고 인증된 정상 종료를
요청한다. 종료가 확인될 때까지 잠금을 유지하고 rollback한다. DB 행은 쓰지 않는다.

RUNNING이라는 표시는 실제 프로세스 생존의 증거가 아니다. 단, 임의로 무시하지 않는다.
검토한 기록 전체의 SHA256이 설정과 일치하고, 현재 OS 부팅 전의 동기 execute이며,
복구 가능한 background job이 없는 경우만 과거 고아 기록으로 보존할 수 있다.
현재 부팅 이후 실행, 다른 종류의 미완료 작업, 활성 세션 lease·전송 예약은 계속 차단한다.
종료된 UNKNOWN과 Claim도 원래 그대로 보존하며 정비를 이유로 완료·삭제·재전송하지 않는다.
미해결 deploy/service_control 효과는 별도 확인 없이 허용하지 않는다.

새 Core는 정비 중 신규 접수와 주기 실행, 시작 시 고아 복구, 라벨 알림을 보류한다.
재개 시 기존 복구 절차를 다시 사용한다. 기존 작업·영수증을 초기화하지 않는다.

## 설치·검증·한계

설정은 별도로 보관한 정책 해시, runtime, Python, 허용 명령, 릴리스 manifest,
검증된 DB schema, 보존 기록 지문을 고정한다. 지문이 달라지면 새 증거를 검토해야 한다.
스키마 지문만으로 데이터 호환성을 주장하지 않고 복사 DB 기동 시험을 함께 수행한다.
묶음은 Python과 psutil에 의존하지만 Core 코드에는 의존하지 않는다.

예약 supervisor는 별도 maintenance/supervisor.json이 설치되면 그 안의 고정 launcher를
해시 확인 후 실행한다. 설치되지 않은 환경은 기존 경로를 유지한다. 손상된 현재 payload는
독립 CLI로 정상 보관판에 복구할 수 있다. current.json 자체가 해석 불가하거나 DB가 손상된
경우, DB 스키마 변경·데이터 복원·보호된 다른 runtime cutover는 자동 처리하지 않는다.

배포 순서는 격리 테스트 → 정확한 후보 CI → 정본 main 통합 → 운영 전환 → 실제 외부 정비
확인 → 접수 재개 → 원격 main 게시·CI 확인이다. 운영 결과는 별도의 설치 영수증으로 남긴다.

## Review a new release registration

Use the read-only planner from a reviewed source checkout with its src directory
on PYTHONPATH:

    python scripts/plan_maintenance_release_registration.py --config CONFIG --review REVIEW.json --source-worktree CLEAN_RELEASE_WORKTREE

The administrator's review record includes the existing config_sha256, candidate
and rollback commit SHAs, candidate_manifest_sha256, rollback_manifest_sha256,
and schema_sha256 from a backup verified with both releases. Record the exact
candidate CI and backup/restore evidence in the review before preparing the JSON.
Include admission_releases only for members of this pair whose maintenance
admission contract was independently verified. The planner checks the submitted
pins against current files and state and emits proposed settings for review.
It does not obtain evidence of CI or database restore success.

Before installing proposed settings through the administrator-controlled
maintenance configuration, recheck the prior config hash, current release,
review evidence, and affected admission pins. Preserve an exact copy of the
prior config for rollback. Treat installation as a separate protected effect.
Require both releases to pass the installed launcher's gates before stopping
Core. Use verify --target SHA --source-worktree CLEAN_RELEASE_WORKTREE for the
candidate and verify --target SHA for the retained release. After activation,
verify the installed candidate without --source-worktree. Recover from
the retained release using the regular maintenance receipts and gates.

## Pin a separate Core Python environment

For a release that needs different Python packages, the administrator prepares a
native interpreter under RUNTIME/python-environments/ENVIRONMENT. Use a private
virtual environment with include-system-site-packages=false. On Windows use
an interpreter process whose PID owns the listening endpoint. A venv redirector
that launches a separate child PID does not satisfy the readiness identity check.

Provision all dependencies before hashing the environment with
bct_maintenance.service_runtime.python_environment_digest. Record the result in
the local administrator-owned RUNTIME/config/core-python-pins.json. The schema
is 1 with a releases object keyed by full source SHA. Each entry has
manifest_sha256, environment (a directory name under python-environments),
executable (a relative path inside that environment), and environment_sha256.
After the pin exists, changing a dependency requires a reviewed replacement
environment and digest. Existing releases without a pin keep the established
Python. Leave the base interpreter and its packages available for rollback.

Use verify for the retained release and verify with --source-worktree for the
candidate. Check the reported python_binding for each before stopping Core.
Install a compatible independent maintenance launcher and supervisor together
before activating a release that requires the pin. Both use the same controller
to check the resolved executable and verify that the started process owns it.


## Risk-based release

Use the installed independent launcher for a clean, exact local main. Pass
the current SHA, target SHA, GitHub Actions run ID and one operation ID.

    maintenance.cmd release --expected-current <running-sha> --target <main-sha> --ci-run <run-id> --operation-id <id>

Pass release-plan instead of release to the frozen launcher to inspect the
committed diff classification. Presentation changes can inherit the running
release's schema and Python binding. Reviewed feature modules require the full
regression run and a verified LIVE backup. Other changes are HIGH and require
--review with the candidate and rollback, current configuration SHA-256,
both manifest hashes, database schema SHA-256, admission release SHAs and the
path and SHA-256 of the compatibility receipt. The receipt records both exact
releases starting on the rehearsal DB and preserved history. A reviewed schema
migration also pins the resulting schema and proves rollback can start with it.

Pause acknowledgment, quiescence, verified LIVE backup and exact service
identity apply to every rollout. Use the original operation ID to inspect
a terminal result. Reconcile an interrupted or ambiguous rollout from its
original journal under runtime/maintenance/rollouts and retain all child
receipts. A proven activation rollback cites the original activation operation
when resolving its effect.
