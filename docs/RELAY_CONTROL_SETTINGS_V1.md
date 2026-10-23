# BCT 릴레이 제어 설정 V1

이 설정의 목적은 경로·함수·단계 순서·인자·메시지 참조를 바꿀 때마다 소스를 수정하고
main 병합·CI·Core 배포를 반복하지 않도록 하는 것이다. 최초 설정 엔진 구현과 새로운 실행
어댑터 추가는 정상적인 소스 작업 대상이다. 이미 등록된 기능의 조합과 값 변경은 운영 설정
수정으로 처리한다.

## 현재 범위

운영 설정 문서 `D:\BCT\runtime\config\relay-message-settings.json`에 선택적인 `control`
구역을 함께 둔다. 기존 `defaults`와 `projects` 메시지 설정은 그대로 유지한다.

V1은 다음을 제공한다.

- 재사용 함수: `driver`, `call`, effect 분류, 기본 인자, timeout
- 경로 그래프: 시작 단계, 호출 함수, 단계별 인자, 저장 이름, 조건 자료, 결과별 다음 단계
- 반복 경로: loop를 허용하되 `max_steps`로 항상 상한 지정
- 선택 경로: `worker_roundtrip` 같은 목적 이름을 실제 route에 연결
- 프로젝트 override: 전역 설정을 보존하면서 특정 scope의 값·함수·route 일부만 깊은 patch
- AI 편집: 읽기 전용 미리보기와 중첩 merge-patch 제안
- 저장: 기존 BCT `write`의 exact SHA CAS와 UTF-8 원자적 쓰기 재사용

V1 제어 설정은 아직 실행기에 연결하지 않는다. 미리보기는 항상
`execution_connected=false`, `effect=NONE_PREVIEW_ONLY`를 반환하며 RCC, CDP, Chrome, BCT
capability 또는 대화 노드를 호출하지 않는다. 다음 구현에서 실행기를 연결할 때도 설정은
권한을 새로 부여하지 않으며 현재 Work 권한과 외부 효과 경계를 별도로 통과해야 한다.

## 예시

```json
{
  "version": 1,
  "defaults": {},
  "projects": {},
  "control": {
    "version": 1,
    "enabled": false,
    "variables": {
      "message_template": "${task}"
    },
    "functions": {
      "compose.worker": {
        "driver": "message",
        "call": "compose.worker",
        "effect": "pure",
        "arguments": {"template": "${message_template}"},
        "timeout_seconds": 5
      },
      "submit.selected": {
        "driver": "rcc",
        "call": "delivery.start",
        "effect": "external",
        "arguments": {"text": "${worker_message.text}"},
        "timeout_seconds": 30
      },
      "observe.reply": {
        "driver": "cdp",
        "call": "evaluate.reply_state",
        "effect": "read",
        "arguments": {},
        "timeout_seconds": 15
      }
    },
    "routes": {
      "worker.roundtrip": {
        "entry": "compose",
        "max_steps": 40,
        "steps": {
          "compose": {
            "use": "compose.worker",
            "save_as": "worker_message",
            "next": {"APPLIED": "submit"}
          },
          "submit": {
            "use": "submit.selected",
            "next": {"APPLIED": "observe", "UNKNOWN": "END"}
          },
          "observe": {
            "use": "observe.reply",
            "guard": {"until": "${reply.complete}"},
            "next": {"PENDING": "observe", "APPLIED": "END"}
          }
        }
      }
    },
    "selected_routes": {
      "worker_roundtrip": "worker.roundtrip"
    },
    "projects": {}
  }
}
```

위 예시는 특정 제품 경로를 확정하지 않는다. `submit.selected.driver`와 `call`, 경로 단계,
인자와 메시지 참조를 설정으로 바꿀 수 있음을 보여 준다.

## AI 편집

전체 제어 설정 미리보기:

```powershell
python -m bct.relay_settings control network.example
```

전역 함수의 호출 이름과 선택 route 일부 변경 제안:

```powershell
python -m bct.relay_settings propose-control - `
  '{"functions":{"submit.selected":{"driver":"chrome_api","call":"tabs.sendMessage"}},"selected_routes":{"worker_roundtrip":"worker.roundtrip"}}'
```

프로젝트 하나의 함수나 단계 인자만 깊은 patch:

```powershell
python -m bct.relay_settings propose-control network.example `
  '{"functions":{"submit.selected":{"call":"tabs.sendMessageForProject"}},"routes":{"worker.roundtrip":{"steps":{"submit":{"arguments":{"channel":"project"}}}}}}'
```

제안 명령은 파일을 쓰지 않는다. 반환된 `new_content`, `expected_sha256` 또는
`expected_absent`를 기존 BCT `write`에 전달한다. 저장 뒤 같은 `control` 명령으로 새 SHA와
resolved preview를 확인한다. 준비되거나 시작된 흐름은 설정 변경으로 소급 수정하지 않고,
다음 시작 전 흐름부터 새 설정을 읽는다.

## 편집 단위

- `variables`: 메시지와 인자에서 참조할 JSON 값
- `functions`: 어떤 driver의 어떤 call을 어떤 기본 인자로 사용할지 정의
- `routes`: 단계 그래프와 결과별 이동
- `selected_routes`: 업무 목적과 route 연결
- `projects`: 특정 scope의 깊은 부분 override

문자열의 `${...}`는 그대로 보존한다. 실제 변수 해석과 함수 availability 확인은 향후 실행기
연결 단계의 책임이다. 설정 미리보기는 존재하지 않는 외부 함수가 실행 가능하다고 주장하지
않는다.
