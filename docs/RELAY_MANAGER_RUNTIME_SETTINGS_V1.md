# BCT 영속 릴레이 — AI Manager 실시간 설정 V1

이 기능의 사용자: 프로젝트를 진행 중인 AI Manager. 사용자는 목표·범위·완료 기준을 제시하고, Manager가 필요한 지시문을 편집한다.

## 정본 설정
운영 경로: D:\BCT\runtime\config\relay-message-settings.json
환경 변수: BCT_RELAY_SETTINGS_PATH (정확한 사용자 정의 경로가 필요한 경우)
파일이 없으면 코드에 있는 검증된 기본값 사용. 파일이 있는데 잘못되면 전송 전에 거절.

기본 JSON 예시:

{
  "version": 1,
  "defaults": {
    "manager_action": "이번 업무 결과 전문을 검토하고 후속 업무가 필요하면 BCT를 통해 실제 전송하세요.",
    "include_pending": true,
    "pending_limit": 6,
    "manager_sections": ["context", "worker_result", "action"]
  },
  "projects": {
    "network.d3052e031bf748d8b1640b566a5bb86b": {
      "worker_return_instruction": "이번 업무에서 실제로 처리한 조치와 결과를 전문으로 반환하세요."
    }
  }
}

지원 필드: worker_intro, worker_return_instruction, manager_intro, manager_action,
manager_sections(정확히 context/worker_result/action), include_pending, pending_limit(0~12).
변경은 프로젝트별 overrides나 defaults에서만 하며, 실행 권한을 확대하지 않는다.

## AI 작업
1. BCT read로 파일 원문과 SHA256을 조회한다.
2. 수정하려는 항목만 조정하고 나머지 설정을 보존한다.
3. BCT write의 expected_sha256/expected_absent로 원자적 변경과 동시 편집 충돌을 검사한다.
4. 필요하면 python -m bct.relay_settings [scope_id] 명령으로 읽기 전용 유효성 검사 및 설정 표시.
5. 변경된 설정은 다음에 확정하는 Worker 지시 또는 Manager 반환에만 적용하고, 기존 제출은 변경하지 않는다.
6. 문제가 생기면 보존한 이전 정상값을 CAS로 복원한다.

## AI Manager 부분 수정 미리보기 (추가 설정 서버 없음)

이 명령은 파일에 쓰지 않으며, 변경된 설정 전문과 BCT write에 사용할 정확한 CAS 인자를 반환한다.

    python -m bct.relay_settings propose network.d3052e031bf748d8b1640b566a5bb86b "{\"pending_limit\": 3}"

- stdout의 expected_absent=true이면 BCT write에서 expected_absent=true로 신규 파일을 생성한다.
- stdout의 expected_sha256 값이 있으면 BCT write에서 expected_sha256에 동일한 해시를 전달한다.
- stdout의 new_content 전체를 write.content로 보낸다. 예상치 못한 수정이 들어가면 쓰기를 거절한다.
- new_sha256 및 effective_preview는 적용 예상 결과를 점검하는 용도다. effect=NONE_PREVIEW_ONLY는 실질적 변경이 없다는 뜻이다.
- 값이 null이면 해당 기본값 또는 프로젝트 override를 제거하고, 내장 기본 설정이 적용된다.
- 파일을 저장한 다음 같은 범위에서 기존 python -m bct.relay_settings <scope_id> 조회로 반영 상태를 확인한다.
- 롤백은 저장 전에 보존한 이전 정상 원문을 BCT write의 새로운 expected_sha256으로 한 번 복원한다. 이미 제출한 Worker 지시/Manager 반환에 소급하지 않는다.

이 흐름은 "설정 확인 → 변경안 만들기 → 기존 BCT write CAS → 다음 미제출 업무"이다.
BCT execute 및 write는 작업에 실제로 위임된 허용 경로·capability가 있어야 한다.
이 명령은 권한을 확대하거나 다른 Work의 파일에 접근하지 않는다.

## 전달 계약
- BCT relay_browser → 기존 RCC delivery-start/status/return/manager-status.
- 이번 Worker 업무 처리 결과 전문은 저장된 원문 그대로 Manager 메시지에 삽입한다.
- Manager 메시지의 맥락·행동 지시와 결과 전문을 하나로 제출하며 별도 정상 Wake 메시지를 보내지 않는다.
- 현재 사용자에게 허용된 Work 범위와 대화 UUID를 다시 확인한다.
- 정확한 원문·대상·Delivery ID는 제출 후 불변이고 불확실하면 재전송하지 않는다.
- 본 구현의 긴 전문이 현재 입력 한도를 넘을 경우 잘라서 보내지 않고 명확하게 실패한다.
- 실제 후속 Worker 제출은 Manager가 접근할 수 있는 기존 BCT 도구로 실행하고 확인해야 한다. 일반적인 FOLLOW_UP 문장만으로 자동 전송했다고 주장하지 않는다.

V1은 메시지 구성/관찰 옵션을 먼저 설정화한 기반이다.
기존 검증·영수증 조회 방식의 추가 설정화는 각 알고리즘에 안전한 선택지가 구현된 범위에 한해 순차적으로 확장한다.
