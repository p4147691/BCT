> **현재 운영 규칙 — 2026-10-30 우선 적용:** [측정 증거·작업 지속 정책](../../MEASUREMENT_EVIDENCE_AND_PROGRESS_POLICY.md) 및 루트 `AGENTS.md`가 이 실행계획의 과거 UNKNOWN/Claim/HOLD 설명보다 우선한다. 측정 결과의 정확성 증거가 없으면 `MEASUREMENT_UNVERIFIED`로 무효 처리하고 그 결과만으로 Claim·작업 중단·재시도 금지를 만들지 않는다. 원인 측정기를 고치면서 다른 진단·개발을 계속한다. 일반 메시지 중복은 수신 노드가 판단하며, 실제 고위험 외부 변경만 정확한 대상과 사용자 승인으로 보호한다. 아래 과거 실행·영수증·시험 서술은 역사로 보존하며 현행 권한 부여 규칙이 아니다.

# BCT Conversation Network drag order

상태: LOCAL_VERIFIED / CI_PENDING / LIVE_NOT_APPLIED

## 범위

- 선택된 Monitor 노드 카드는 노란 테두리만 사용하고 내부를 노랗게 채우지 않는다.
- 대화망 노드를 고스트 프레임으로 끌고 카드 사이의 밝은 삽입선을 보고 놓을 수 있게 한다.
- 같은 대화망 안에서는 표시 순서를 바꾸고, 다른 대화망 제목이나 카드에 놓으면 그 범위로 이동한다.
- 순서는 BCT의 기존 conversation UUID 레코드에 `display_order` 하나로 저장한다. 새 권한, 라우팅 신원,
  대화망 registry 또는 N번호 의미를 만들지 않는다.
- 범위 이동은 기존 membership 이력을 EXCLUDED로 보존하고 Manager 등 안내 태그를 유지한다.

## 안전 경계

- Chrome 탭 순서와 실제 대화 제목은 변경하지 않는다.
- RCC, Native Host, Relay binding 및 기존 UNKNOWN/Claim은 변경하지 않는다.
- 서버는 정확한 UUID와 대상 범위를 검증하고 순서 및 선택적 범위 이동을 한 트랜잭션에서 처리한다.
- exact-head CI 성공 뒤에만 Core와 Monitor 설치본을 같은 SHA에서 배포한다.

## 수락 조건

1. 선택 카드가 노란 테두리만 보인다.
2. 드래그 중 원본은 흐려지고 별도 고스트 프레임이 포인터를 따른다.
3. 삽입 전/후 위치는 밝은 선 하나로 구분된다.
4. 새로고침 뒤에도 같은 대화망의 표시 순서가 유지된다.
5. 대화망 간 이동 시 N번호와 안내 태그가 유지되고 이전 membership 이력도 남는다.
6. 잘못된 UUID, 존재하지 않는 범위, 범위가 섞인 순서 요청은 부분 반영 없이 거부된다.

## 로컬 검증

- Python 전체 회귀: 898 PASS
- 집중 conversation network / Monitor runtime: 29 PASS
- Monitor BCT shell, node interaction, thumbnail overlay: PASS
- Monitor 관련 독립 계약 17개 PASS
- `check_monitor_desktop_visual.js`: 생성 산출물인 Native Host exe가 worktree에 없어 실행 불가
- `check_monitor_ncodex_rdp_route.js`: 이미 제거된 legacy N-CODEX 문구를 요구하는 기존 stale 검사로 현재 main에서도 불일치
- JavaScript syntax, Python compileall, `git diff --check`: PASS
