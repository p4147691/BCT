# RCC Rebuild V2-1 — 차단 레거시 일괄 제거

상태: `SOURCE_COMPLETE / CI_PASS / RCC_LIVE_UNCHANGED`

## 범위

정책이 이미 차단한 background/content 분기와 그 분기에서만 도달하던 구현을 source에서
한 번에 제거했다. Simple Relay V0, exact conversation 읽기, bounded diagnostics, 기존
fail-closed 오류 계약은 유지했다. tab/window mutation Adapter는 source에 보존했지만 active
loader에서는 불러오지 않는다.

이번 단계에서는 `D:\ChromeExtensions\RCC\extension`, Chrome, Native Host, Relay binding,
대화 탭과 storage를 변경하지 않았다.

## call graph와 제거 결과

- `background.js`: 5,103줄에서 2,080줄로 축소
- `content.js`: 4,458줄에서 1,780줄로 축소
- 선언된 named function 중 파일 내부 참조가 선언 1회뿐인 함수: 두 파일 모두 0개
- 제거한 background helper 60개, content helper 62개
- 제거한 과거 ACT bootstrap/registration/rename/direct-tab/general delivery/orchestration 경로의
  구현 테스트 16개는 활성 계약 테스트로 대체된 상태를 확인한 뒤 같이 제거

활성 native command는 `ping`, `state`, Simple Relay `bind/send/return`, `rename-receipt`,
`result`, read-only capture/probe/diagnostics와 bounded extension reload 계약으로 한정했다.
활성 runtime message는 pending/state/activity 조회로 한정했다. content router는 recovery,
activity/probe, Simple Relay execute/read-reply만 유지한다.

## active bundle

- background loader: Core, read-only Browser Adapter, Relay, network policy, background entrypoint
- content scripts: `relay_core.js`, `content.js`
- 제외: optional browser mutation Adapter, `act_bridge.js`, `act_content.js`,
  `act_command_bridge.js`

optional Adapter 파일과 영수증 계약 테스트는 삭제하지 않았다. 로딩되지 않는다는 경계도
architecture test로 고정했다.

## 검증

- `node --check` background/content: PASS
- 남은 RCC JavaScript 테스트 20개 전수: PASS
- focused Python RCC source 계약 13개: PASS
- Simple Relay 및 route Adapter 회귀: PASS
- architecture boundary 및 legacy command policy: PASS
- `python -m compileall -q src tests`: PASS
- `git diff --check`: PASS

exact source commit은 `46f1772ecddb2079198101692b40eb5155f87b1e`이며 GitHub Actions
`BCT CI` run `39388085496`의 preflight, Core 4개 shard와 browser-bridge가 모두 통과했다.
V2-2 전에는 source를 LIVE RCC 설치본에 복사하거나 확장을 reload하지 않는다.

같은 시점에 별도로 밀린 BCT Core 배포 후보를 감사했다. 이전 LIVE `c2e7d39` 이후 runtime
프로필에 포함되는 실제 코드 변경은 opt-in compact/hybrid MCP catalogue뿐이었고, RCC 변경은
프로필에 포함되지 않았다. durable `bct_deploy` operation
`bct-live-deploy-20261020-46f1772`가 exact commit을 generation 165로 APPLIED했다. production
catalogue는 기존 full 44-tool 기본값을 유지했다. RCC 설치본 3개 파일과 Native Host 실행 파일
SHA-256, RCC instance/session, 열린 대화 UUID와 tab identity는 배포 전후 동일했다.
