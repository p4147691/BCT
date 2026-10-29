# RCC 1.0.59 → 1.0.60 파비콘 LIVE 준비 — N73

## 정본과 보호 경계

- 감독관 통합 main 기준: `aaa3982e0b57c8d789189f5499215a4c77884d3e`.
- 기존 기능: PR #352 파비콘 렌더러와 PR #354 Core→RCC 이벤트 계약은 main에 이미 들어 있음. 다시 병합하지 않음.
- 이번 격리 후보: 해당 main에서 PR #351 HEAD `59d5b2c47a73b00eb4169b62e08cf859ee700971`을 코드 보존 방식으로 통합.
- 실제 설치 RCC `D:\ChromeExtensions\RCC\extension`은 **1.0.59 / 57파일**, source manifest는 **1.0.60 / 후보 58파일**.
- 이번 단계는 오프라인 파일·해시·실행 계약 준비. 운영 Chrome·RCC·Core 재시작, 확장 설치·리로드, 공유 main·LIVE 변경 없음.

## 설치된 1.0.59 실제 보존

기존 54개 롤백 기준에는 실제 설치에 존재하는 다음 세 파일이 빠져 있었음.

- `browser/tab_group_adapter.js`
- `browser/tab_group_contract.js`
- `domain/tab_group_service.js`

기존 기준의 SHA와 실제 설치 SHA가 다른 파일은 정확히 10개:

`background_loader.js`, `boot/platform_context.js`, `browser/tab_move_contract.js`, `content/content_router.js`, `content/conversation_dom.js`, `domain/endpoint_service.js`, `domain/readonly_diagnostics.js`, `legacy/command_policy.js`, `manifest.json`, `platform/browser_gateway.js`.

실제 설치의 **57개 전체 파일을 독립 스냅샷으로 바이트 그대로 복제**하고 각각 SHA를 비교함. 스냅샷 경로:

`D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\rollback_installed_1_0_59`

복사 직전 원본 릴리스 명세와 파일별 이전·현재 차이는 같은 상위 폴더의 `previous_manifest.json`, `comparison_report.json`에 보존.

- 롤백 57파일 aggregate: `5e278244216f5a9e9a0d21a10236b923d4bc9f5b4c712a100e6c62d9691c7bda`
- 통합 후보 58파일 aggregate: `e42d6d0241e275c45b0d61c05db6711891ce42ce4b6394ba2219e67af694f3d9`
- 격리 후보: `D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\candidate_source_1_0_60`
- 후보에만 추가되는 런타임 파일: `domain/node_favicon_notify_service.js`.

두 스냅샷 모두 `verify_release_candidate.py --live-root <rollback> --candidate-root <candidate>` 실행으로 **exact 57/58, 해시, loader graph, command matrix, extension ID, rollback plan** 통과. 이 문서는 백업 증거이지 LIVE 배포 영수증이 아님.

## PR #351·#354 기능 정합화

실제 소스 `content/content_router.js`에서 PR #351의 `renameDiagnostic` 반환과 PR #354의 `relay:nodeLabelNotify`가 공존하는 것을 검증. `content/conversation_rename.js`, `domain/conversation_rename_service.js`, `test_conversation_rename_diagnostics_n72.js`를 보존.

릴리스 명세 `rcc_v2_rc.json`의 충돌은 **어느 한쪽의 이전 해시를 선택하지 않고**, 최종 통합된 파일에서 candidateInventory/aggregate/activeLoaderGraph를 다시 계산하고, **실제로 설치된 57파일 전체**로 rollbackBaseline을 다시 생성함. `ROLLBACK.md`에 이번 57파일 기준을 보강하고 SHA도 갱신.

동일 확장 ID와 공개 키·Native Host 경계를 유지한다. 사용자 스크립트·대화 제목·node-sync·UNKNOWN·Claim 계약은 수정하지 않음.

## Tampermonkey 실제 사용 여부

BCT에서 운영 Chrome의 `chrome-extension://dhdgffkkebhmkfjojejmpbldmpobfkfo/background.js` 서비스 워커가 존재하는 것은 확인함. 즉 **Tampermonkey 확장 서비스 워커 존재 증거**는 있으나, `browser_extension_manage(operation=list)`는 `TAMPERMONKEY_OPTIONS_PAGE_REQUIRED`로 실패. 정확한 사용자 스크립트 설치 목록과 PR #352 스크립트 활성화 여부는 **미확인**이다. 이번 작업은 기존 Chrome 탭·포커스를 변경하거나 옵션 페이지를 임의로 열지 않았다.

이는 최종 READY_FOR_LIVE 결격 조건일 수 있다. 감독관은 승인된 Tampermonkey options 경로에서 원본과 설치된 script ID·SHA·enabled·@match 상태를 확보하고, 구형 15/30초 CDP favicon writer 소유권과 중복을 판정해야 한다.

## 감독관의 설치·롤백·실사용 수락 절차

1. 격리 후보 정확 HEAD CI 및 local main, PR #351 기여 파일, RCC release candidate verifier PASS를 확인한다.
2. 설치 바로 전 **그 시점의** 운영 확장 ID·실제 설치 경로·확장 버전·파일 57개 전체 SHA를 재검사한다. 현재 스냅샷과 다르면 HOLD; 덮어쓰거나 캐시로 추정하지 않는다.
3. Chrome 프로필의 Tampermonkey script 존재·정확한 버전과 중복 감시기 상태를 공식 BCT read-only 경로에서 확정하고, 승인 없는 script 등록/삭제/업데이트·확장 재로드를 금지한다.
4. 보호된 BCT 설치 도구를 통해서만 exact 후보 58개를 한 번에 원자적 적용하고, 이전 57개 스냅샷을 복구 가능하게 유지한다. 확장 같은 ID·권한·Native Host 동작 및 Core/RCC 각각 실제 실행 SHA를 기록한다.
5. 승인된 same-ID RCC reload 후 정확한 ChatGPT 탭 UUID/번호 N아이콘(실제 Chrome 탭 픽셀), 백그라운드 이벤트 ACK, SPA 이동, 중복 UUID fail closed, 원래 제목·포커스·본문 불변, RCC 송수신·ACK를 실사용 E2E로 증명한다.
6. 미일치/UNKNOWN/영수증 누락 시 추가 반복 설치를 중단한다. 이전 exact Core/RCC release 및 확장 57개 파일로 롤백한 뒤 SHA 검증과 원본 receipt·Claim 보존. 확장·Chrome/profile 데이터를 불필요하게 삭제하거나 node-sync를 수정하지 않는다.

## 재현 명령

격리 worktree의 `scripts/prepare_rcc_favicon_live_n73.py`는 **읽기 전용 설치 트리**를 비교하여 새 `--snapshot-root`로 원본 57개와 후보 58개를 복제하고 manifest를 생성한다. 기존 스냅샷 폴더가 존재하면 덮어쓰지 않고 실패한다. 정확한 소스/롤백 검증:

```powershell
python modules/rcc/release/verify_release_candidate.py --live-root D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\rollback_installed_1_0_59 --candidate-root D:\BCT\data\RCC_FAVICON_PREP_N73_20261029\candidate_source_1_0_60
```

**최종 판정은 감독관이 Tampermonkey 설치 증거와 LIVE 실사용 수락 범위에 따라 별도로 결정한다.**
