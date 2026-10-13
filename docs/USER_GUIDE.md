# BCT 사용 안내

## 평소 사용법

별도 명령 문법을 외울 필요는 없다. Codex에 원하는 결과를 평소 말로 요청하면 된다.
Codex는 BCT work와 operation을 만들고 읽기, 수정, 실행, 테스트, commit, GitHub 통합,
배포와 검증을 필요한 범위에서 이어서 수행한다.

상태 화면은 `http://127.0.0.1:18790/monitor`에서 볼 수 있다. 서비스 확인 주소는
`http://127.0.0.1:18790/health`, MCP 주소는 `http://127.0.0.1:18790/mcp`이다.

## 자동으로 가능한 일

- 프로젝트 조사와 파일 읽기
- 시스템과 프로세스 상태 확인
- Python, PowerShell, 일반 프로그램 실행
- 장시간 Python/PowerShell/프로그램 세션 시작과 상태 확인
- Laya 추천 조회와 Monitor 상태 확인
- 기존 operation 결과와 GitHub PR 상태 조회

폴더 내용은 파일 읽기와 구분해 `bct_read`의 `operation: "directory_tree"`로 조회한다.
경로는 현재 work의 허용 root 안에 있어야 하며, 기본 깊이는 2, 기본 최대 항목 수는 200이다.
결과는 파일(`file`)·하위 폴더(`directory`)·따라가지 않는 링크/재분석 지점(`symlink`)을 구분한다.

같은 조사 단계에서 여러 파일이나 폴더가 필요하면 `operation: "batch"`와 `items`를 사용해
한 번에 조회한다. 각 항목에는 고유한 `id`와 절대 경로를 넣고, 폴더 항목만
`operation: "directory_tree"`, `depth`, `limit`을 추가한다. 한 batch는 최대 20개 항목이며
파일당 512 KiB, 파일 내용 합계 1 MiB, 폴더 요청 한도 합계 2,000개로 제한된다. 결과는 입력
순서를 유지하고 항목별 SHA·관측 시각·성공 또는 오류를 반환한다. receipt에는 파일 본문이
저장되지 않으므로 동일 operation을 다시 조회해도 과거 본문은 복원되지 않는다.

일반 작업에서도 안전 조건과 승인 경계가 같은 읽기·비교·상태 확인은 가능한 한 묶어서 처리한다.
이미 받은 상태나 receipt를 불필요하게 다시 조회하지 않는다. 쓰기, 승인, 병합, 배포,
UNKNOWN 처리와 정확한 SHA 확인은 각각의 안전 경계를 유지한다.

이 실행들도 BCT receipt, 정확한 작업 루트, PID/fingerprint, timeout과 중복 방지 기록을 남긴다.

## 주의 메시지가 필요한 일

파일 변경, 프로젝트 코드 테스트, Git commit, GitHub push/merge, LIVE 배포, 서비스 재시작,
Chrome/RCC mutation처럼 지속되는 부작용이 있는 단계에서는 Codex가 대상과 영향을 보여줄 수
있다. 이 경고는 도구가 없어서 멈추는 것이 아니라 실제 변경 직전의 안전 경계다.

## 위치

- 공식 소스: GitHub `p4147691/BCT`의 `main`
- 로컬 main checkout: `D:\BCT\source`
- 운영 release: `D:\BCT\runtime`
- 상태와 receipt: `D:\BCT\data`
- 모델: `D:\BCT\models`
- 로컬 LLM dependency: `D:\BCT\local-llm`
- 격리 worktree: `D:\BCT\worktrees`

초기 `D:\PROJECTS\BCT` bootstrap 복구본과 연결 worktree는
`D:\Archive\BCT-Bootstrap-20261013`에 보존되어 있다. 새 격리 작업은
`D:\BCT\worktrees` 아래에 만들고, GitHub main 통합 후 `D:\BCT\source`를 동기화한다.

## 문제가 생겼을 때

먼저 Monitor와 health를 확인한다. 같은 operation ID를 임의로 다시 실행하지 말고 기존 receipt를
조회한다. BCT의 배포와 서비스 작업은 exact SHA, backup, health, rollback 증거를 사용한다.
ACT를 먼저 종료하거나 Chrome profile/binding을 초기화할 필요는 없다.
