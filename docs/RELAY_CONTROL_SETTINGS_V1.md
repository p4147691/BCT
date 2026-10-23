# BCT 릴레이 제어 설정 V1

이 설정은 메시지 문구뿐 아니라 **어떤 등록 함수와 경로를 사용할지**를 운영 중에 바꾸기
위한 것이다. 등록된 선택지의 인자·문구·목적별 경로를 조정할 때는 소스 수정, main 병합,
CI, Core 재배포가 필요하지 않다. 새로운 어댑터를 처음 추가하거나 안전 경계를 바꾸는 경우만
정상적인 소스 통합 대상이다.

운영 파일은 `D:\BCT\runtime\config\relay-message-settings.json` 하나다. 기존 `defaults`와
`projects` 메시지 설정 및 선택적인 `control` 설정을 함께 보관한다. 저장은 기존 BCT `write`의
exact SHA CAS와 UTF-8 원자적 쓰기를 그대로 사용한다.

## 실행 경계

설정은 Python import, 임의 capability 호출 또는 권한 추가 수단이 아니다. 실행기는
`driver`/`call`을 아래 고정 레지스트리에서만 찾는다. 선택된 기존 capability는 현재 Work와
Principal 정책을 다시 통과해야 한다.

| driver / call | 실제 기존 기능 | 효과 |
| --- | --- | --- |
| `message / compose.worker` | BCT 표준 Worker 메시지 구성 | pure |
| `rcc / delivery.start` | `relay_browser`의 `delivery-start` | external |
| `rcc / delivery.cancel` | `relay_browser`의 `delivery-cancel` | external |
| `rcc / delivery.status` | `relay_browser`의 `delivery-status` | read |
| `rcc / delivery.return` | `relay_browser`의 `delivery-return` | external |
| `rcc / delivery.manager_status` | `relay_browser`의 `delivery-manager-status` | read |
| `rcc / delivery.preview` | 기존 Delivery 메시지 미리보기 | pure |
| `rcc / state` | RCC 상태 조회 | read |
| `rcc / send.to_tab` | 기존 탭 직접 제출 | external |
| `cdp / list_pages` | `cdp_inspect`의 탭 목록 조회 | read |

`chrome_api / tabs.sendMessage`처럼 레지스트리에 없는 이름은 설정으로 저장할 수는 있어도
실행 가능하다고 표시되지 않으며, 호출 전에 실패한다. 해당 어댑터를 실제로 추가하려면 별도
소스 검토가 필요하다. 이는 특정 경로를 금지하는 의미가 아니라 존재하지 않는 구현을 설정
문자열만으로 만들어 냈다고 가장하지 않기 위한 경계다.

한 `relay_control` 호출은 pure 단계 여러 개 뒤에 **기존 BCT operation 단계 하나만** 실행한다.
외부 효과가 둘 이상 필요한 왕복은 다음 목적처럼 나눈다.

- `worker_submit`: Worker 메시지 구성 및 한 번 제출
- `worker_status`: Worker 결과 상태 한 번 조회
- `manager_return`: 확인된 Worker 결과를 Manager에게 한 번 반환
- `manager_status`: Manager 응답 상태 한 번 조회

따라서 대기 중 상태를 짧은 루프로 연속 조회하거나 제출과 반환을 한 호출에 섞지 않는다.
각 단계는 독립된 operation ID와 영수증을 가지며 `UNKNOWN`을 새 ID로 재전송하지 않는다.
Browser Bridge는 이 레지스트리와 현재 실행 경로에 포함하지 않는다.

## 예시

```json
{
  "version": 1,
  "defaults": {},
  "projects": {},
  "control": {
    "version": 1,
    "enabled": true,
    "variables": {"rcc_instance": "RCC_INSTANCE_ID"},
    "functions": {
      "submit.worker": {
        "driver": "rcc",
        "call": "delivery.start",
        "effect": "external",
        "arguments": {
          "instance_id": "${rcc_instance}",
          "delivery_id": "${delivery_id}",
          "manager_conversation_key": "${manager_conversation_key}",
          "worker_conversation_key": "${worker_conversation_key}",
          "scope_id": "${scope_id}",
          "text": "${task}"
        },
        "timeout_seconds": 30
      },
      "inspect.tabs": {
        "driver": "cdp",
        "call": "list_pages",
        "effect": "read",
        "arguments": {}
      }
    },
    "routes": {
      "worker.submit.rcc": {
        "entry": "submit",
        "max_steps": 1,
        "steps": {
          "submit": {"use": "submit.worker", "next": {"APPLIED": "END"}}
        }
      },
      "browser.inspect.cdp": {
        "entry": "inspect",
        "max_steps": 1,
        "steps": {
          "inspect": {"use": "inspect.tabs", "next": {"APPLIED": "END"}}
        }
      }
    },
    "selected_routes": {
      "worker_submit": "worker.submit.rcc",
      "browser_inspect": "browser.inspect.cdp"
    },
    "projects": {}
  }
}
```

실행 시 `purpose`, `scope_id`, `context`, 미리보기에서 확인한
`expected_settings_sha256`를 `relay_control`에 전달한다. 실행기는 해당 revision과 해석된 하위
요청을 operation 시작 전에 고정한다. 같은 operation ID는 정확히 같은 요청에만 재사용한다.

## AI 편집

전체 제어 설정과 레지스트리 일치 여부 확인:

```powershell
python -m bct.relay_settings control network.example
```

전역 선택 경로와 timeout 변경 제안:

```powershell
python -m bct.relay_settings propose-control - `
  '{"functions":{"submit.worker":{"timeout_seconds":45}},"selected_routes":{"worker_submit":"worker.submit.rcc"}}'
```

프로젝트 하나의 단계 인자만 변경 제안:

```powershell
python -m bct.relay_settings propose-control network.example `
  '{"routes":{"worker.submit.rcc":{"steps":{"submit":{"arguments":{"text":"${task}"}}}}}}'
```

제안 명령은 파일을 쓰지 않는다. 반환된 `new_content`와 `expected_sha256` 또는
`expected_absent`를 기존 BCT `write`에 전달하고, 저장 뒤 다시 `control`로 revision과
`runtime_availability`를 확인한다.

## 변경 적용 범위

- 문구, 변수, 등록 함수 alias, 기본 인자, timeout, 목적별 route, 프로젝트 override:
  다음에 시작하는 호출부터 즉시 적용; main/CI/Core 재배포 불필요
- 이미 시작되어 영수증이 만들어진 operation: 당시 설정 SHA와 요청을 유지
- 새 RCC/CDP/API 어댑터, 새 capability, 권한 또는 중복 효과 규칙 변경:
  소스 검토와 정상 통합 필요
- 비어 있거나 `enabled=false`인 control: 실행 차단, 메시지 설정 기능은 계속 사용 가능

`guard`와 한 route 안의 복수 operation 단계는 V1 실행기에서 지원하지 않는다. 미리보기용
설정에 존재하더라도 실제 실행 전 실패한다. 반복 조회는 목적별 호출로 수행한다.
