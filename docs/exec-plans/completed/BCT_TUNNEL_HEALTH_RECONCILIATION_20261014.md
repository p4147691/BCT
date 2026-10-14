# BCT Tunnel Health Metadata 복구 완료

상태: `COMPLETE / LIVE_ACCEPTED`

## 장애와 원인

운영 tunnel 프로세스와 dispatcher는 정상 동작했지만 health URL discovery 파일이 없어졌다.
그 결과 `tunnel-client runtimes status`가 실제 process 상태와 다르게
`healthy=false / starting`을 표시했고, supervisor는 이미 살아 있는 tunnel에 중복 connect를
시도했다. 중복 process는 기존 process와 충돌해 시작되지 않았다.

원인은 운영과 같은 `act-control` profile, alias, health URL 파일을 사용한 격리 진단
instance였다. 진단 instance가 시작하면서 운영 discovery 파일을 덮었고 종료하면서 삭제했다.
따라서 이 사건은 dispatcher 중단이 아니라 진단 환경과 운영 환경 사이의 metadata 충돌이다.

## 반영된 보호 규칙

1. supervisor는 executable, tunnel ID, MCP target이 모두 일치하는 process를 먼저 확인한다.
2. exact process가 살아 있으면 discovery 파일 부재만으로 두 번째 tunnel을 시작하지 않는다.
3. 파일 복구에는 exact PID가 소유한 loopback listener만 사용한다.
4. 후보 listener가 정확히 하나이고 `/healthz=live`, `/readyz=ready`일 때만 파일을 원자적으로
   복구한다.
5. 후보가 없거나 둘 이상이면 `BCT_TUNNEL_DEGRADED`로 닫힌 상태를 유지한다.
6. 개발·진단 tunnel은 운영과 다른 profile directory, alias, health URL 파일을 사용한다.

이 규칙은 process identity와 health metadata를 분리한다. metadata가 낡거나 없어졌다는 이유로
정상 process를 종료하거나 교체하지 않는다.

## 검증 결과

| 검증 | 결과 |
| --- | --- |
| focused module/recovery tests | 8 PASS |
| 단일 exact PID listener에서 discovery 복구 | PASS |
| 같은 PID에 유효 listener 2개인 경우 | fail closed, 파일 미작성 |
| 전체 로컬 회귀 | 113 PASS / 120.790초 |
| compile 및 diff 검사 | PASS |
| PR #74 required CI | PASS |
| main CI run `38482851054` | PASS |
| Hosted ChatGPT read-only E2E | `FINISHED / APPLIED` |

PR #74는 `3418bfa9b6eee46d488682bc34fad431e883a8a2`로 병합됐고 같은 SHA가
LIVE Core에 배포됐다. LIVE manifest는
`26fe6b2f7f08bddf18035816baaf5c393b7be287cfb94fc2505dc87827d2bd85`다.

운영 tunnel PID `20852`와 시작 시각 2026-10-13 19:18:27 KST는 변경되지 않았다. 최종
`tunnel-client runtimes status act-control --json`은 `healthy=true`, `ready=true`,
`runtime_state=ready`, `stale=false`였고 두 loopback probe가 모두 HTTP 200을 반환했다.

## 종결 판정

원래 acceptance의 모든 조건이 충족됐다. 운영 tunnel은 중단·교체하지 않았고, 원래 반영
과정에서도 supervisor host만 다시 시작했다. 후속 단일 E2E
`bct-mcp-latency-root-e2e-read-01`도 `FINISHED / APPLIED`로 끝났다. 이 계획을 `active/`에서
`completed/`로 이동하며 추가 복구 작업은 남기지 않는다.
