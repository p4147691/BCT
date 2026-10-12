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
