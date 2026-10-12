# BCT Foundation — first slice complete

상태: FIRST_SLICE_COMPLETE / CI_PASS.

## 완료 범위

- core 공통 계약, 정책, SQLite 상태, node/connection revision, work handoff.
- durable operation, exact duplicate guard, unresolved-effect resource claim.
- bounded UTF-8 file read와 expected SHA/absence 기반 atomic write.
- Python `py_compile`과 `unittest`; 출력 원문은 durable receipt에 저장하지 않음.
- expected HEAD, exact dirty set, new-file SHA proof 기반 Git commit.
- BCT 소스는 ACT Python package를 import하지 않음.

## 검증

- 로컬 13 tests PASS.
- 실제 disposable Git 흐름: read → edit → re-edit → create file → test → commit PASS.
- wrong principal, duplicate ID, concurrent writer, UNKNOWN duplicate guard, stale file SHA/HEAD, foreign dirty, symlink escape, safe handoff PASS.
- `python -m compileall -q src tests` PASS.
- `git diff --check` PASS.
- GitHub Windows CI run `38234473954` PASS.

## 다음 범위

GitHub 통합 기능을 BCT 소스로 이전한다. 현재 GitHub main/PR/CI/canonical sync 계약을 먼저 확인하고, 이 first slice의 정책·operation 체계를 재사용한다.

MCP, RCC, deployment/service와 ACT LIVE 전환은 아직 시작하지 않았다. 기존 운영 연결과 데이터를 보존한다.

