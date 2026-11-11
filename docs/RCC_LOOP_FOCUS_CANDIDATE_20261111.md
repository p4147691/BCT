# RCC Loop Focus — 별도 배포 후보 검증 기록 (2026-11-11)

## 범위 및 소유권

- 원본 요청: Work `bct-loop-recipe-20261111`, Direction `direction-6fdb6878f4484275aafd37b3`
- RCC 수정 전용 PR: #472, `fix/loop-rcc-focus-20261111`
- 변경 소유: `modules/rcc/extension/content/simple_relay_executor.js`, 해당 테스트, **새 후보** 릴리스 기록.
- N42 소유 영역인 `src/bct/features/rcc.py` 및 인수·계측, 기존 Operation 계약은 변경하지 않는다.
- 기존 `modules/rcc/release/rcc_v2_rc.json`은 기록 보존. SHA-256 `e792a81e8b628481e1765bcf9d77cd1e1988bced24f3d70fa89882a22439b34d`.
- 기존 candidate inventory aggregate `e054f0fae6598c64c2eb0e4ff397740ffa76acba50abe06dd2e78dfb288e1f02` 보존.

## 새 후보 및 릴리스 핀

- 후보: `RCC_LOOP_FOCUS_SETTLE_20261111`.
- Manifest: `modules/rcc/release/rcc_loop_focus_20261111.json`.
- Manifest SHA-256: `599f8d356ab43054103bfeafaba84177b22faeeda6b0b9239057bb837a992c2e`.
- 별도 핀: `modules/rcc/release/rcc_loop_focus_20261111.pin.json`.
- 58파일 aggregate SHA-256: `2a73b20116f40bcbfa99fdf2dc6b46ccccbd4c16decc5965788a9c240fc5d516`.
- 유일하게 변경된 콘텐츠 스크립트: `content/simple_relay_executor.js`, 42845바이트, SHA-256 `c2b0764a11e96e533d8709245468af992520520b95fdbf6a73baa9e0875492ea`.
- 구 릴리스 rollbackBaseline·rollbackPlan 및 계약 증거는 새 후보에서도 바뀌지 않는다.

## 완료한 검증

기존 CI 실패 3건에 해당하는 strict 테스트를 새 후보로 전환해 각각 PASS. 구 후보 manifest 자체의 불변 SHA, 구 인벤토리 aggregate, 후보 간 lineage, 신규 manifest SHA 핀, 전체 58개 파일 크기·해시를 추가 검사해 PASS. 단순 검사 삭제나 해시 비교 생략은 없다.

격리 staged payload: `D:\BCT\worktrees\loop-rcc-focus-stage-20261111`. 기존 검증기의 `verify(..., candidate_root=stage)`로 58/58 `stagedCandidateVerified=true` 확인. 이는 설치본이 아니며 `installedCandidateVerified=false`다.

## 실제 RCC E2E 차단 및 후속 승인

기존 실제 테스트의 첫 신규 대화 전송은 APPLIED. 동일 UUID 두 번째 기존 탭 전송 두 건은 확정 NOT_APPLIED(`RELAY_EDITOR_FOCUS_OR_CARET_INVALID`). 별도 검토 탭 최초 전송 UNKNOWN은 재전송하지 않는다.

이번 콘텐츠 스크립트 변경은 **운영 Chrome/RCC에 설치되지 않았다**. 별도의 패치된 Chrome 확장을 실행하려면 기존 운영 RCC 연결과 분리된 Chrome 프로필, 확장·네이티브 호스트 인스턴스/파이프, ChatGPT 인증 테스트 대화, 정확한 대상·응답 영수증을 안전하게 확보해야 한다. 기존 확장은 설치 ID가 고정되어 있고 nativeMessaging/Windows named pipe를 사용하므로 단순한 별도 프로필만으로 무간섭이 증명되지 않는다. 완전 격리 증거 없이는 설치·재로드 금지.

정확 SHA 전체 CI 성공과 독립 Supervisor 검수, 실제 동일 UUID 2회 이상 다중 턴·복구 E2E PASS 이전에는 PR 병합, main·LIVE·운영 확장 변경 금지.
