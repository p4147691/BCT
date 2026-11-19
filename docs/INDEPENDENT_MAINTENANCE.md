# BCT 없이 정비하기 — 구현 위치와 사용 경계

상태: **격리 후보. 운영 미설치·미적용.** 이 문서는 소스 기능 안내이며 실제 검증 결과는
`INDEPENDENT_MAINTENANCE_VALIDATION.md`에 별도로 기록한다.

## 무엇이 달라지는가

기존에는 외부 Python에서 정비 코드를 불러와도 `bct` 패키지 초기화가 먼저 실행됐다.
이 후보는 정비 구현을 `bct_maintenance`라는 독립 패키지로 옮긴다. BCT 본체가 import
오류로 시작하지 못해도 정비 도구는 실행된다. 기존 BCT 호출부도 이 패키지를 사용하므로
배포·프로세스 제어 구현을 두 벌 유지하지 않는다.

소스 읽기·수정·Git·로컬 테스트에는 BCT가 필요하지 않다. 공유 main 통합, 배포 및 복구는
별도의 권한·충돌 확인·정확한 버전 검증이 필요하다. 외부 경로가 이를 생략하지 않는다.

## 기능 지도

| 기능 | 구현 위치 | 입력 → 출력 | 바꾸는 것 |
|---|---|---|---|
| 기존 배포 검증 부품 | `src/bct_maintenance/releases.py` | 정책·SHA·릴리스 → 검증된 manifest | 검증은 읽기 전용; staging/pointer 함수는 명시적 쓰기 |
| 공통 배포 엔진 | `src/bct_maintenance/engine.py` | 기존/후보 SHA → 배포 결과 | 릴리스, current 포인터, 서비스, 배포 영수증 |
| 공통 프로세스 제어 | `src/bct_maintenance/service_runtime.py` | 런타임·서비스·포트 → 상태/결과 | 해당 Core 프로세스와 service 영수증 |
| 공통 배타 잠금 | `src/bct_maintenance/locking.py` | 런타임 경로 → 잠금 | `state/maintenance.lock` |
| 외부 정비 명령 | `src/bct_maintenance/cli.py` | 검토된 설정·명령·정비 ID → JSON | 아래 명령별로 구분 |
| 외부 재기동 부품 | `src/bct_maintenance/supervisor.py` | 런타임·프로필 → 상태 | 검증된 현재 릴리스 기동; pause 시 거부 |
| 별도 보관용 묶음 생성 | `scripts/build_maintenance_bundle.py` | 작업공간 artifacts 경로 → 독립 폴더 | 해당 artifacts 아래만 생성. 운영 설치 없음 |
| BCT 기존 경로 연결 | `src/bct/features/deploy.py` | 기존 Work/Operation → 기존 형태의 결과 | 공통 엔진 호출. RCC 경로는 기존 구현 유지 |
| 신규 작업 접수 중지 | `src/bct/core/store.py`, `src/bct/runtime_server.py` | 정비 pause 파일 → 접수/주기 실행 보류 | 기존 영수증 보존. 정상 운영에는 영향 없음 |

`src/bct/service_runtime.py`는 호환 import 경로다. 기존 호출자·예외 클래스의 동일성을
유지한다. 모델 오류 클래스는 독립 `errors.py`에서 공유한다.

## 외부 명령이 정확히 하는 일

모든 명령은 명시적인 `--config`가 필요하다. 기본 운영 대상이나 자동 활성화는 없다.

| 명령 | 동작 | 중요한 거부 조건 |
|---|---|---|
| `status` | 포인터·프로세스·DB의 미완료 건수 조회 | 관측 실패는 UNVERIFIED로 표시 |
| `verify --target SHA` | 보관 릴리스 해시와 DB 호환 승인 확인 | 변조, 미승인 릴리스, 미검증 DB 스키마 |
| `reconcile --operation-id ID` | 과거 정비 기록과 지금 상태 비교 | 기록 없음. 재실행하거나 UNKNOWN을 해제하지 않음 |
| `backup` | 정지 상태에서 SQLite backup API로 일관된 사본 생성 | 실행 중인 DB writer, 미완료 작업, 미해결 Claim |
| `start` | 승인된 현재 릴리스 기동 | 잘못된 포인터·해시·DB 호환성, 이미 실행 중 |
| `stop` | health의 신원이 확인된 Core에 정상 종료 요청 | 정비 접수 중지 미확인, 미완료 작업, 미해결 Claim |
| `stop-unresponsive` | 명시한 fingerprint와 일치하는 무응답 Core만 종료 | PID·생성 시각·실행 파일·명령줄·runtime 불일치. 자식/다른 프로세스 종료 안 함 |
| `recover --target SHA` | 보관된 승인 릴리스로 포인터 전환 후 기동 | Core 미정지, 호환성 미검증, 손상된 복구 대상 |
| `activate --target SHA` | 깨끗한 정본 main 후보를 기존 배포 엔진으로 배포 | 미검증 후보, 예상 현재 SHA 불일치, 보호된 runtime cutover |

쓰기 명령에는 `--operation-id`와 `--expected-current`가 필요하다. 완료한 동일 요청은
기록만 반환한다. 다른 요청에 같은 ID를 재사용할 수 없다. STARTED/UNKNOWN이 남으면
새 ID로 우회할 수 없다. 실패 후 정지 상태를 확인하고 별도 복구를 수행할 때만
`recover --resolves 기존ID`로 원본 기록을 연결한다. 원본 UNKNOWN은 덮어쓰지 않는다.

## 운영 작업 보존

- 실제 운영 DB는 `mode=ro`로 확인한다. Store 초기화나 migration을 호출하지 않는다.
- RECORDED/RUNNING Operation 또는 unresolved Claim이 하나라도 있으면 외부 변경을 거부한다.
  현재 버전은 보수적인 전체 점검이다. 자원별 선별 허용은 아직 제공하지 않는다.
- `BCT_CORE_SUPERVISOR.STOP`과 `BCT_MAINTENANCE.PAUSE`가 모두 있어야 쓰기 명령이 가능하다.
  CLI는 이 파일을 자동으로 만들거나 제거하지 않는다. 실제 정비 창에서 별도 검토 후 설정한다.
- pause는 새 Operation 접수와 주기적 복구 실행을 보류한다. 이미 시작한 작업을 종료하거나
  결과를 지우지 않는다. 기존 작업이 끝나지 않았다면 정비가 거부된다.
- 실행 중 Core를 종료할 때는 접수 중지 계약을 시험한 SHA여야 한다. 정상 종료는 health의
  `maintenance_contract=1` 및 `maintenance_paused=true`까지 확인한다. 이전 운영판에
  pause 파일만 만들어 놓고 안전하게 정지할 수 있다고 간주하지 않는다.
- DB를 자동으로 과거 버전으로 복원하지 않는다. 코드 복구와 데이터 복구는 다르다.
- Chrome/RCC/Monitor, 로그인, 브라우저 탭, 다른 process session은 변경 대상이 아니다.

## 설정과 독립 보관

설정에는 정책 경로와 SHA256, 정확한 runtime, Python 경로, 허용 명령, 검증한 릴리스의
manifest SHA256 및 호환 DB schema SHA256, 접수 중지 계약을 검증한 릴리스 목록이 들어간다.
이는 로컬 운영자의 승인 문서이며 암호학적 사용자 인증을 새로 제공하는 시스템은 아니다.
파일 접근 권한은 운영 계정 수준으로 보호해야 한다. 실제 운영 설정은 이 후보에서 만들지 않는다.
영구 복구 설정의 정책 파일은 현재 Core 릴리스 내부가 아닌, 별도로 검증·보관한 사본을
가리켜야 한다. 현재 릴리스 전체가 손상돼도 정책을 읽을 수 있어야 하기 때문이다.
DB 스키마 지문 일치는 호환성 증명 자체가 아니다. 호환 목록은 복사 데이터의 기동·복구
시험 결과로 승인해야 한다. 구조가 같아도 데이터 의미가 달라진 버전은 별도 검증한다.

묶음 생성 예시(격리 작업공간에서만):

```powershell
python scripts/build_maintenance_bundle.py --output artifacts/maintenance-candidate-final
python artifacts/maintenance-candidate-final/run.py --help
```

묶음에는 정비 패키지와 해시 manifest만 들어간다. 운영 DB·토큰·설정은 포함하지 않는다.
`run.py`는 각 소스의 해시를 확인한 뒤 독립 패키지를 import한다. Python과 psutil은 별도
설치 의존성이다. 정비 묶음은 Core 릴리스와 별도 위치에 고정해서 보관해야 한다.
현재 예약 작업은 자동 변경하지 않는다. 기존 supervisor 경로를 유지하며, 독립 감시
경로로의 운영 전환은 별도 설치·검증 대상이다.

## 이번 후보의 명시적 한계

- 설치·운영 전환 전이다. 기존 Core가 이미 이 기능을 사용한다고 설명하면 안 된다.
- 손상된 **payload**에서 정상 보관본으로 복구할 수 있지만, `current.json` 자체를 읽을 수
  없거나 DB를 열 수 없는 경우는 증거가 부족하므로 변경을 거부한다.
- DB schema를 바꾸는 배포와 DB 복원, 보호된 다른 runtime으로의 cutover는 자동 수행하지 않는다.
- 자동 복구 시험은 임시 폴더·포트·테스트 프로세스에서 수행한다. 사용자 브라우저가 연결된
  실제 운영 Core의 고장·복구 시험은 운영 적용 승인 전에는 수행하지 않는다.

## 운영 전환 전 확인 순서

1. 정확한 후보 SHA의 회귀 테스트와 필수 CI 완료. 정책상 GUARDED_CI_FIRST 대상이다.
2. 실행 중인 작업과 미해결 효과를 개별 확인. 일괄 상태 변경·Claim 삭제 금지.
3. 기존 운영판에서 접수 중지 계약이 없다는 점을 고려한 최초 전환 창을 별도로 확보.
4. 독립 묶음을 Core와 별도 위치에 설치하고 읽기 전용 상태 대조. 운영 권한 설정 검토.
5. 복사 DB의 후보 기동·이전판 호환성 시험 후 승인된 schema/릴리스 목록 작성.
6. 사용자가 결과를 확인한 뒤 실제 변경 승인. 정확한 백업·복구 경로로 Core만 전환.
7. 실제 동작과 진행 중이던 작업의 연속성 확인 후 pause 해제. 설치·기동·기능 수용을 각각 보고.
