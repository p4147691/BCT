# ChatGPT N번호 파비콘 — 격리 후보 0.1.2

기존 자산 재사용: D:\BCT\data\chatgpt-node-favicon.user.js (0.1.1)
원본 SHA256: a5066cb12b4a49dd1a0da729af537d02035f80e2c1760b92683cd7fde296f419
이 디렉터리의 userscript는 배포 전 소스이며 원본/운영 Chrome과 RCC를 수정하지 않는다.

## 동작 및 안전 경계
- Core /monitor/state의 대화 UUID, 단일 OPEN 탭, tab_id/window_id, 실제 탭 URL, N번호를 교차 확인한다.
- 중복 UUID, 노드 미등록, 신원 불일치, Core/RCC 오류는 fail-closed로 원래 favicon을 보존한다.
- 실제 Chrome tabId는 userscript에서 알 수 없어 동일 UUID의 복수 탭은 표시하지 않는다.
- SPA Navigation API, popstate/hashchange, pageshow/focus, visibilitychange, head mutation을 감지한다.
- 선택적 window 이벤트 bct:conversation-roster-changed는 반드시 Core의 현재 상태 재조회만 유도한다.
- 15초/30초 폴링과 일체의 주기적 상태 조회 타이머 없음. 제목/본문/RCC 메시지/포커스 조작 없음.

## 검증 명령
- node modules/rcc/favicons/test_chatgpt_node_favicon.cjs : 19개 모의 회귀
- node modules/rcc/favicons/test_chatgpt_node_favicon_browser.cjs : 별도 headless Chrome/profile PNG 64×64 검증
- python -m unittest discover -s tests -p test_rcc_favicon_userscript.py -v : CI core shard에서 위 Node 모의 시험 실행
- 격리 브라우저의 DOM/PNG PASS는 운영 Chrome 탭 스트립 시각 확인과 구별한다.

## 감독관 배포 전 차단
1. 기존 RCC/BCT가 bct:conversation-roster-changed를 발행하는 영수증은 없다.
   백그라운드 노드 등록 변경의 즉시 반영을 수락하려면 승인된 이벤트 연결을 검증해야 한다.
   15초/30초 폴링 재도입 금지.
2. Tampermonkey 목록 읽기는 TAMPERMONKEY_OPTIONS_PAGE_REQUIRED로 실패.
   실제 설치 상태 및 기존 CDP watcher와 중복 갱신 경쟁을 감독관이 확인한다.
3. 2026-10-23 기존 문서의 DOM 6/6 PASS는 운영 Chrome 탭 숫자 픽셀 확인이 아니다.
   운영 N70/N71 및 중복/미등록 탭의 화면 표시, 제목 및 RCC 전달을 별도 실사용 수락한다.
4. main 병합, LIVE, 운영 Chrome 확장 설치·재로드·사용자 탭 변경은 감독관 전담.

## 범위 분리
기능 소스와 JS 검증은 modules/rcc/favicons/ 아래이며 CI 연결 테스트만 tests/test_rcc_favicon_userscript.py를 사용한다. PR #349 Monitor 모듈화 파일은 수정하지 않는다.
기존 데이터의 userscript 0.1.1도 원형 보존.

## 후속 검증: RCC 이벤트 연결과 기존 감시기
- RCC observation_gateway.js는 Chrome 탭 생성·갱신·삭제·이동을 받으며, endpoint_service.js는 host:endpoints snapshot/delta를 Native Host로 전송한다. 여기에는 Core의 N번호가 없다.
- BCT monitor_runtime.py는 /monitor/state 조회 시 ensure_observed_node_labels로 N번호를 구성한다. 해당 결과를 사용자 스크립트에 알리는 bct:conversation-roster-changed 발행자·전달 경로는 현행 소스에서 확인되지 않았다.
- 기존 CDP watcher는 15/30초 폴링과 data-bct-cdp-favicon-20261023을 사용한다. 후보 userscript는 data-bct-node-favicon-v1만 변경하며 다른 아이콘 태그를 삭제하지 않는다. 기존 watcher 등록 세션은 RUNNING으로 남아도 해당 PID들은 실존하지 않는 것으로 관측되었다. 운영 프로필·중복 설치 여부는 미검증이다.
- 새 모의 회귀 5개 추가로 총 19/19 PASS: 백그라운드 등록·해제 이벤트, 백그라운드 SPA 이동, 옛 CDP 태그 공존, 이벤트가 없으면 배경 변경이 반영되지 않고 포커스 때 복구되는 한계.
- 실제 노드 등록 변경 시 이벤트 미발행이므로 배경 탭 즉시 업데이트는 미수락. 별도 폴링 추가 금지; 감독관이 확정할 이벤트 공급 계약 없이는 READY_FOR_DEPLOY 아님.
