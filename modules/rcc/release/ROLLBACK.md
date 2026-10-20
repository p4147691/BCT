# RCC Rebuild V2 Release Candidate — backup/rollback 절차

이 문서는 V2-4의 비-LIVE 검증 계약이다. 지금 실행하는 배포 스크립트가 아니며, V2-5의 별도
명시 허용 전에는 설치본, Chrome, Native Host, binding을 변경하지 않는다.

## 고정 대상

- source payload: `D:\BCT\source\modules\rcc\extension`
- LIVE extension: `D:\ChromeExtensions\RCC\extension`
- backup root: `D:\BCT\runtime\backups`
- extension ID: `ocbidbaplechjjdacmokhnfbdmgjkphf`
- Native Host: `com.ai_workspace_relay.host`

## V2-5 배포 전 조건

1. GitHub `main`의 exact SHA와 해당 SHA의 BCT CI 성공을 확인한다.
2. `verify_release_candidate.py --live-root D:\ChromeExtensions\RCC\extension`으로 후보와 현재
   rollback 기준선이 모두 일치하는지 확인한다. 불일치하면 중단하고 기준선을 임의 갱신하지 않는다.
3. LIVE extension과 backup/staging의 resolved path가 각각 위 고정 root 안인지 확인한다.
4. 현재 LIVE 전체 디렉터리를 새 operation 전용 backup 디렉터리에 복사하고, V2-4 rollback
   inventory와 파일 수·파일별 SHA-256·aggregate SHA-256을 다시 대조한다.
5. 후보 파일만 포함한 staging 디렉터리를 만들고 candidate inventory와 exact 일치하는지 확인한다.
   Native Host executable/manifest, Chrome profile, storage와 binding은 staging 대상이 아니다.

## 단일 전환

1. 검증된 staging을 동일한 LIVE path에 한 번만 전환한다. 부분 파일 배치나 모듈별 reload는 하지 않는다.
2. same-ID unpacked extension을 정확히 한 번 reload한다.
3. 읽기 전용 `state`와 `probe`로 build, extension ID, Native Host, Manager/Worker UUID와 binding을 확인한다.
4. mismatch, ambiguous 또는 UNKNOWN이면 실제 relay를 보내지 않고 rollback으로 이동한다.

## rollback

1. 추가 reload나 전송을 먼저 시도하지 않는다. 현재 효과를 읽기 전용으로 대조한다.
2. LIVE path를 별도 quarantine 이름으로 보존한 뒤, 검증된 exact backup 전체를 원래 LIVE path로 복원한다.
3. 복원 payload를 rollback inventory로 다시 검증하고 same-ID extension을 한 번만 reload한다.
4. 읽기 전용 `state`와 `probe`로 이전 build, extension ID, Native Host, UUID, storage와 binding 연속성을 확인한다.
5. 복원 여부를 증명할 수 없으면 `UNKNOWN`으로 남기고 후보나 backup을 재복사하지 않는다.

Native Host와 Chrome profile은 이번 payload 전환의 변경 대상이 아니므로 rollback에서도 덮어쓰거나
재등록하지 않는다. backup은 V2-5 acceptance와 rollback 가능성이 모두 확인될 때까지 삭제하지 않는다.
