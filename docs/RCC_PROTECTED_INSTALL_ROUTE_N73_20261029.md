# RCC 설치·same-ID 재로드·롤백 보호 호출 경로 — N73 격리 개발

## 판정과 재사용 근거

- 기준 main SHA: `cdff046db810f9c65e2a35941e21cdb70261f4d2` (PR #355 포함).
- PR #355의 57파일 실제 설치본·58파일 통합 후보·SHA·릴리스 manifest는 **수정/재생성하지 않음**.
- 기존 `deploy` BCT capability는 **Core 런타임 릴리스**를 전환한다. RCC 확장 설치 디렉터리 전환 기능은 없었다.
- 기존 `relay_browser(command="reload-extension")`는 RCC Core Work/Operation을 통과해 정확한 인스턴스의 유지보수 재로드를 수행한다. 해당 기능은 **중복 개발하지 않음**.
- 기존 `file_action_apply`는 단일 파일만 처리하고 보호 경로를 차단하므로 57/58파일 확장 설치에는 사용 불가.

이번 별도 브랜치는 기존 `DeployFeature`에 명시적인 3개 operation만 추가하고, 같은 기능의 Work/Operation·policy·resource claim·영수증을 재사용한다. 신규 MCP 도구·새 감시기·상주 폴링 없음.

## 설치 관리 명령: 기존 BCT deploy API

보호된 Core 릴리스가 최종 인계 후보를 받아 설치된 **이후에만** 다음 BCT `deploy` 명령들이 사용 가능하다. 현재 실행 중인 Core에 이미 노출됐다고 가정하지 않는다. 설치 시에는 새 Core 릴리스의 `deploy` capability를 통해서만 호출한다.

- `operation="rcc-inspect"`: 설치 전 read-only 57/58파일, exact extension ID·버전·manifest·rollback SHA 검사.
- `operation="rcc-install"`: BCT에서 검증된 기존 deploy Work·Operation 안에서만 57→58파일 전환. 디스크 journal에 이전 상태·백업·격리 원본 및 단계별 SHA 기록. **Chrome reload 호출 없음**.
- `operation="rcc-rollback"`: 이전 설치 Operation ID에 정확히 연결된 설치본 58→57파일 복구. 기존 57파일 원본을 그대로 보존. **Chrome reload 호출 없음**.

허용되는 인자는 `operation,expected_source_head,expected_installed_aggregate,expected_candidate_aggregate,expected_manifest_sha256,instance_id`, rollback시에만 `install_operation_id`. 다른 파일 경로·임의 설치본·권한·대상 선택·중복 Operation은 거부한다.

정본 고정 경로:

- 설치 경로: `D:\ChromeExtensions\RCC\extension`
- 58파일 후보: `D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\candidate_source_1_0_60`
- 정확한 57파일 원본: `D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\rollback_installed_1_0_59`
- PR #355 고정 릴리스 manifest: `D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\release_manifest_pr355_immutable.json` (SHA-256 `8b0b4419339f349eb729160154842d6bdf8676f4699c480feda92762bd4a8871`). 현재 main의 manifest와 혼동하거나 새 57/58파일 후보를 재생성하지 않는다.
- 작업별 journal/backup: `D:\BCT\runtime\backups\rcc-guarded-install`

기존 릴리스 manifest에서 검증된 원본 57개 aggregate SHA:
`5e278244216f5a9e9a0d21a10236b923d4bc9f5b4c712a100e6c62d9691c7bda`

후보 58개 aggregate SHA:
`e42d6d0241e275c45b0d61c05db6711891ce42ce4b6394ba2219e67af694f3d9`

RCC ID: `ocbidbaplechjjdacmokhnfbdmgjkphf`. 버전 1.0.59 → 1.0.60.

## 원자성 한계와 실패 복구

Windows 디렉터리 이름 바꾸기는 개별 연산 단위로 원자적이다. **원본→격리와 stage→운영 두 번의 전환 전체가 하나의 전원 장애 내성 트랜잭션은 아니다.** 이 사실을 단일 atomic switch 성공이라고 보고하지 않는다.

1. 설치 전 파일별 SHA 및 전체 hash를 이중 확인한다. 임의 링크·정본 경로 변경·중복 journal을 차단한다.
2. 같은 볼륨의 운영 경로 형제 폴더에 stage를 복제하고 58파일을 다시 확인한다. 57파일 백업도 복사·재검증한다.
3. fsync한 새 journal에 `PREPARED`를 저장한다. 기존 journal이 있으면 설치를 거부한다.
4. 정확한 기존 운영 폴더를 `.rcc-previous-<operation>`으로 이동한다. 이후 stage→운영 전환·재검증한다.
5. 성공 시 `INSTALLED_AWAITING_RELOAD`를 반환한다. 이는 **파일 적용 대기 완료만** 뜻하며 재로드/LIVE PASS가 아니다.
6. 중간 예외·전원 차단은 오리지널 journal·backup·quarantine을 남기고 UNKNOWN을 반환한다. 새 ID 재시도로 성공이라고 주장하지 않는다.
7. 보호된 rollback Work·Operation으로 `ROLLBACK_AWAITING_RELOAD`까지 복구한 뒤 검증한다. Chrome 재로드는 별도 기존 명령으로 단 한 번 실행한다.

## 승인된 순서 (감독관 전담; 이 격리 개발에서 실행하지 않음)

1. 이 후보의 정확한 HEAD CI PASS와 Core 배포 후의 `deploy` 신설 명령 노출 여부를 확인한다.
2. 운영 Core/RCC 및 Tampermonkey 설치 영수증, 현재 브라우저 profile, RCC 정확 instanceId를 검증한다.
3. BCT Work에 **`deploy`와 `relay_browser`** 및 설치/root 경로를 명확히 포함한다. 운영 Core policy/Operation이 허용하지 않는 경우 STOP. 위 인자로 읽기 전용 `rcc-inspect`만 먼저 호출한다.
4. 승인 후 고유 Operation ID로 `rcc-install` 정확히 한 번 수행한다. 반환된 `INSTALLED_AWAITING_RELOAD`와 journal을 확인한다. 설치 성공만으로 사용자 탭 수락 선언 금지.
5. 기존 `relay_browser`의 `reload-extension`을 별도 승인된 동일 RCC 인스턴스 Work/Operation으로 정확히 한 번 실행한다. RCC reconnect 후 read-only `state`·`probe`로 실제 1.0.60 build/UUID·세션 및 ACK를 확인한다.
6. Chrome 실제 탭 헤더 N번호 픽셀, 백그라운드 변경 알림, 제목·포커스·본문 보존, 기존 메시지 송수신 E2E를 검증한다.
7. 실패·UNKNOWN이면 추가 install/reload 재시도 금지. 처음 설치 Operation ID의 영수증/파일 위치를 대조한 뒤 별도의 승인된 `rcc-rollback` 호출과 기존 `reload-extension`을 **명시적으로** 검증한다. 실제 57파일/Chrome 상태가 확인되지 않으면 HOLD/UNKNOWN 보존.

사용자 운영 환경에 대한 설치·재로드·복원·확장 업데이트/프로필 조작은 이번 작업에서 **일절 수행하지 않음**. 원본 PR #355·57/58 후보 해시·node-sync·Claim/UNKNOWN 상태도 보존.

## 검증 범위

`tests/test_rcc_protected_install_route.py`는 운영 설치 디렉터리를 사용하지 않는 임시 폴더에서 사전 검사, Work 스코프, 승인, 진짜 BCT Operation 영수증, 비정상 중단, 중복 금지, 57→58 적용·58→57 복원, 재로드 없음 등을 검증한다. 실제 운영 경로는 읽기 전용 inspect만 실행하고 설치 효과는 0이다.

**INSTALL_ROUTE_READY 판정은 새로운 Core 소스 후보가 통합되어 BCT 배포 기능으로 노출된 뒤에만 운영에서 유효**하다. 배포 전에는 격리 개발 후보의 코드·시험 완료만 증명한다.

## 기존 main이 달라진 경우 고정 manifest 경계

이 격리 작업 중 main의 `rcc_v2_rc.json`이 변경되면서 현재 main은 보존된 PR #355 후보 58파일과 `content/conversation_dom.js`, `domain/exact_tab_send_service.js` 두 파일 SHA가 달라졌다. 설치본 자체와 스냅샷은 무변경이다. 새 installer는 PR #355 통합 SHA `cdff046db810f9c65e2a35941e21cdb70261f4d2`의 JSON 파일을 SHA-256으로 검증해 **별도의 새 참조 사본에 고정**했다. 설치되는 실제 57/58파일과 PR #355 커밋은 수정하거나 재생성하지 않았다. 이후 main 변경이 미리 승인한 고정 설치 후보의 SHA를 무효로 변경하지 못하도록 차단한다.
