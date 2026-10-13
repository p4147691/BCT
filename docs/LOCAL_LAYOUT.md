# 로컬 폴더 구조

이 문서는 `D:\`에서 어떤 폴더가 무엇을 뜻하는지 설명한다. 공식 소스는 각 프로젝트의
GitHub `main`이고, 아래 경로는 로컬 작업·설치·운영 자산의 위치다.

## 최종 기준

| 경로 | 용도 | Git 공식 소스와의 관계 |
| --- | --- | --- |
| `D:\BCT` | BCT 제품의 로컬 checkout, runtime, data, models, worktrees | `D:\BCT\source`가 GitHub `p4147691/BCT` main의 로컬 checkout |
| `D:\PROJECTS` | 사용자가 만드는 독립 제품·앱의 로컬 checkout | 프로젝트마다 자기 GitHub 저장소를 사용 |
| `D:\ChromeExtensions` | Chrome에 실제로 로드하는 설치 payload와 Native Host | 소스 checkout이 아니라 설치 위치 |
| `D:\TOOLS` | 여러 프로젝트가 함께 쓰는 제3자 도구·SDK·실행 파일 | 필요하면 버전과 SHA를 별도 기록 |
| `D:\MODELS` | 제품에 종속되지 않는 공용 모델 자산의 권장 위치 | Git에 넣지 않음 |
| `D:\Archive` | SHA manifest가 있는 되돌릴 수 있는 과거 사본 | 일정 기간 검증 후 삭제 가능 |

프로젝트는 개발·배포 대상이다. 도구는 여러 프로젝트가 호출하는 공용 실행 자산이다.
프로젝트가 완성됐다고 자동으로 도구가 되는 것은 아니다. 공용으로 제공하기로 결정하고
안정된 입력·출력과 버전을 갖춘 경우에만 `TOOLS`로 설치한다.

## BCT 내부

- `source`: GitHub main을 따라가는 깨끗한 로컬 checkout.
- `worktrees`: 수정·테스트용 격리 checkout. 병합 후 제거한다.
- `runtime`: exact main SHA로 만든 불변 Core release와 실행 receipt.
- `data`: operation, session, migration receipt 등 변경 가능한 운영 상태.
- `models`: BCT가 운영하는 Laya weight.
- `local-llm`: Laya 실행에 필요한 버전 고정 dependency.

Core release는 `src/bct` 실행 코드와 읽기 전용 `modules/status-ui`만 포함한다. RCC,
DesktopWindow Monitor, BDC처럼 설치·교체 가능한 기능은 Git 저장소의 `modules/`에서
관리하되 Core release에 복사하지 않는다.

## 현재 정리된 항목

- 과거 ACT checkout/worktree 8개: `D:\Archive\ACT-Legacy-20261013`.
- BCT bootstrap checkout/worktree: `D:\Archive\BCT-Bootstrap-20261013`.
- `AI_TOOLS`의 staging, verify, checkpoint, 과거 Monitor/RCC 사본과 루트 일회성 파일 231개:
  `D:\Archive\AI_TOOLS-Legacy-20261013`.
- `ChromeExtensions`의 비활성 ACT/bridge/review 사본과 루트 임시 파일 19개:
  `D:\Archive\ChromeExtensions-Legacy-20261013`.
- 구형 RCC 소스·설치본·Native Host 트리: `D:\Archive\ACT-Relay-Legacy-20261013`.
- 비활성 ACT/ADC 예약 작업 5개: XML과 SHA manifest를
  `D:\Archive\ACT-Scheduled-Tasks-Legacy-20261013`에 보존한 뒤 예약 작업에서 제거했다.
- GitHub에 남아 있던 오프라인 ACT runner 등록 27개를 exact offline/busy=false 확인 후
  제거했다. 로컬 runner 파일과 Windows 서비스는 이 작업에서 삭제하지 않았다.

각 Archive에는 원래 경로, 파일 수·크기, tree SHA와 Git 정보가 든 manifest가 있다.

## 아직 이동하지 않는 항목

- `D:\ACT`: RCC는 더 이상 이 경로를 사용하지 않는다. 일부 Runner, Chrome Auto Proxy,
  관리자 소유 ADC agent/connector, DesktopWindow Monitor의 구형 backend 계약만 남아 있다.
- `D:\AI_TOOLS`: Quick Hotkey, Chrome 테스트 자산, DesktopCommander와 아직 분류 중인 실제
  프로젝트만 남겼다.
- `D:\ChromeExtensions`: 현재 로드된 확장과 Native Host, 그리고 Git 프로젝트로 이동 여부를
  별도 확인해야 하는 소스 checkout만 남겼다.
- `D:\AI_Models\ollama`: Ollama가 사용하는 대형 모델 저장소라서 설정 전환 없이 이동하지 않는다.

이 항목들은 실행 참조를 제거하거나 대체한 뒤에만 이동한다. 단순히 이름이 낡았다는 이유로
활성 경로를 옮기지 않는다.

## 현재 실행 기준

- BCT Core/MCP: `D:\BCT\runtime`, port 18790.
- BCT Laya: `D:\BCT\models` + `D:\BCT\local-llm`, port 18771.
- BCT RCC 설치본: `D:\ChromeExtensions\RCC`, Native Host는 BCT 고정 extension origin만 허용.
- BCT Monitor: Core의 `http://127.0.0.1:18790/monitor`.
- DesktopWindow Monitor: `D:\ChromeExtensions\DesktopWindow-Monitor`; 현재는 별도 호환 모듈.

GitHub `p4147691/BCT`의 `main`이 제품의 유일한 공식 소스다. `D:\BCT\source`는 그 main을
동기화하는 로컬 checkout이고, `runtime`과 `ChromeExtensions`는 검증된 source SHA로 만든
설치·실행 결과다. 운영 파일을 직접 정본으로 삼지 않는다.
