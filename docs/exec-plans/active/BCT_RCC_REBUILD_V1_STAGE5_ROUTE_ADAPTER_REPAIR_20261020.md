# RCC Rebuild V1 — 5단계 반환 Browser Adapter 보수

## 관측된 사실

4단계 Manager→Worker 단일 원문은 정확히 한 user turn을 추가했고 Worker의 새 assistant
응답도 완료됐다. 그러나 기존 5단계 반환은 ChatGPT 화면에 현재 렌더된 assistant 메시지의
총수를 pre-send count와 비교했다. 긴 대화의 virtualized DOM은 총수를 줄일 수 있으므로,
새 응답이 있어도 `NOT_APPLIED`로 잘못 판정할 수 있다.

해당 반환 요청은 실패 응답 뒤 재전송하지 않았다. Manager에 원문이 전달됐다는 증거가 없으므로
5단계는 완료가 아니다.

## Source 보수

- Simple Relay 제출 시 exact user turn의 이전 turn key 목록과 제출 원문을 `relayActiveExecutionV1`
  기록에 보존한다.
- 제출 직후 exact route turn key를 해석해 보존한다.
- 반환 읽기는 화면 전체 assistant count가 아니라 `resolveRoutedTurn`과
  `recoverCompletedReplyFromDom`으로 해당 user turn의 assistant 응답만 읽는다.
- Native 응답은 원문을 노출하지 않는 compact `relayReceipt` 상태·오류 정보를 함께 제공한다.

## 안전 규칙

이 보수는 source-only다. 새 코드의 CI와 설치 전 검증이 통과하기 전에는 설치본을 바꾸지
않는다. 기존 실패 반환은 재시도하지 않으며, 보수 후 새 operation ID와 새 승인 원문으로만
별도 4→5 수락시험을 수행한다. 5단계 성공 전에는 6단계 Legacy 변경 경로 차단을 활성화하지
않는다.
