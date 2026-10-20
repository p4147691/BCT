# RCC Rebuild V1 — 0단계 기준선 및 비-LIVE 복구 연습

상태: STAGE_0_COMPLETED_NO_LIVE_RELOAD_OR_BROWSER_MUTATION

기록 시각: 2026-10-20 09:44 KST

## 범위

이 작업은 읽기 전용 상태 확인, 설치본 백업, 그리고 별도 임시 디렉터리 복원·해시 비교만
수행했다. 확장 재로드, Native Host 재시작, Chrome 탭 이동·새로 고침, 대화 메시지 전송,
extension storage 변경은 수행하지 않았다.

## 고정된 LIVE 연결 기준선

| 항목 | 확인 결과 |
| --- | --- |
| Chrome extension ID | ocbidbaplechjjdacmokhnfbdmgjkphf |
| version / build | 1.0.23 / 2026-10-20-simple-relay-return-v0 |
| installed extension | D:\ChromeExtensions\RCC\extension |
| manifest SHA-256 | d9cdead8f4cb3abc9686f6217de5eb10f002bdb71025ddf8f5e5ff77ceeae919 |
| Native Host name | com.ai_workspace_relay.host |
| registry manifest | D:\ChromeExtensions\RCC\native\com.ai_workspace_relay.host.json |
| Native Host executable | D:\ChromeExtensions\RCC\native\RelayNativeHostV2.exe |
| Native manifest SHA-256 | f2c2d0f437e4369c617515ec1bba4c7cbef407d176e60ea8616891200abe2228 |
| Native executable SHA-256 | 78087b6a1ece5793be22028c6c002f44eb2fb81f74609d8bf9893b8dae7a1d30 |

Native manifest의 허용 origin은 위 extension ID 하나이며, registry 기본값도 동일 manifest를
가리킨다.

## Relay binding과 대화 상태

Native pipe의 read-only state로 extension storage의 Relay binding을 확인했다.

~~~json
{
  "simpleRelayV0Binding": {
    "version": 0,
    "managerConversationKey": "6ad5afa4-b1e0-83ee-8692-aec4bb51523e",
    "workerConversationKey": "6ad4bb5d-6624-83ee-b045-e57fdad5120e"
  }
}
~~~

두 binding 대상은 각각 정확히 하나의 열린 endpoint로 해석됐고 모두 OPEN, generating false였다.
instance/session/tab/window 값은 이 기록의 주소가 아니라 그 순간의 관측값이므로 영속 binding으로
저장하지 않는다.

## 백업과 복구 rehearsal

| 단계 | 위치 | 결과 |
| --- | --- | --- |
| 원본 | D:\ChromeExtensions\RCC\extension | 32 파일 |
| durable backup | D:\BCT\runtime\backups\rcc-rebuild-v1-baseline-20261020-093700 | extension 32 파일 + Native manifest/executable |
| 비-LIVE rehearsal | D:\BCT\runtime\rehearsals\rcc-rebuild-v1-baseline-20261020-093700 | backup에서만 복원 |

- LIVE extension ↔ backup: 32/32 파일, SHA-256 불일치 0건
- backup ↔ rehearsal: 32/32 파일, SHA-256 불일치 0건
- LIVE Native manifest ↔ backup: 일치
- LIVE Native executable ↔ backup: 일치

이 rehearsal은 임시 디렉터리에서만 수행했다. 백업이나 rehearsal을 삭제하지 않았으며 LIVE
설치 경로로 파일을 되돌리지 않았다.

## source와 설치본의 해석

source extension 디렉터리는 40 파일, LIVE 설치본은 32 파일이다. 차이 12개 중 source에만 있는
9개는 테스트/fixture이고, LIVE에만 있는 3개는 이전 테스트 파일 2개와
background.js.backup-pr226-20261019-01이다. 이들은 manifest/loader가 불러오는 실행 payload가
아니다.

manifest, background loader, background, content scripts, relay core, simple relay, bridge,
popup을 포함한 실행·표시 payload 29개 파일은 source와 LIVE의 SHA-256이 모두 일치했다.
따라서 이 기준선은 “설치 폴더 전체가 source와 동일하다”가 아니라 “실행 payload는 동일하고
비실행 잔존 파일은 명시적으로 분리했다”는 뜻이다.

## 판정

PASS: 기존 연결 identity, Relay binding, 대화 endpoint 상태, Native Host 등록, backup,
비-LIVE 복원 해시가 모두 확인됐다.

다음 허용 작업은 source 안에서만 하는 1단계 Core 분리다. 이 기록에 있는 LIVE 경로, extension
ID, Native Host 등록, Chrome storage, conversation UUID는 1단계에서 변경 금지다.
