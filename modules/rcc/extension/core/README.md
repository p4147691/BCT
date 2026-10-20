# RCC Core V1 — source-only candidate

이 디렉터리는 RCC 재구축 1단계의 순수 Core 후보이다. 현재 manifest와 background loader는 이
파일을 불러오지 않는다. 따라서 여기의 변경은 Chrome 확장, Native Host, storage, 열린 탭,
Relay binding에 효과를 내지 않는다.

| 파일 | 책임 | 하지 않는 일 |
| --- | --- | --- |
| identity.js | ChatGPT URL에서 UUID를 읽고 exact tab 후보를 판정 | binding 저장·다른 탭 대체 |
| state.js | exact tab과 endpoint 관측을 CONNECTED/MISSING/AMBIGUOUS/BUSY 등으로 분류 | probe·inject·reload |
| conversation.js | 제출 intent, ACK, 새 응답 읽기 결과를 순수 계약으로 분류 | DOM 읽기·입력·전송 |
| transport.js | state 요청 모양과 제출 후 효과 상태를 분류 | pipe write·fallback·자동 재시도 |

2단계가 별도로 승인되기 전에는 이 파일을 manifest, loader, background, content.js에 연결하지
않는다. UNKNOWN은 항상 재전송 불가이며 NOT_APPLIED도 새 operation과 재확인 없이는 재시도할 수
없다.
