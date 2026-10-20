# RCC Rebuild V1 — 3A단계 Source Relay 경계

## 목적

RCC의 순수 Core와 실제 Manager↔Worker Relay 계약을 분리한다. 이 단계는 브라우저를
조작하거나 메시지를 전송하지 않는 source-only 구조 작업이다.

## 변경

- `modules/rcc/extension/relay/contract.js`를 Relay 계약의 단일 구현으로 만들었다.
  이 파일은 Manager·Worker의 두 endpoint, operation ID, 원문 길이만 검증하며 Chrome,
  DOM, storage, 전송, 반복 효과를 사용하지 않는다.
- 기존 `simple_relay_v0.js`는 compatibility entrypoint로만 남겼다. loader는 이를 로드하지
  않고 canonical Relay contract를 직접 로드한다.
- `test_architecture_boundaries_v35.js`가 Core와 Relay contract의 browser/storage/effect
  의존성 부재와 loader 경계를 검사한다.

## 의도적으로 남긴 것

`background.js`의 Chrome adapter, receipt persistence, 실제 제출/반환과 노드 생성·큐·자동
ACK·orchestration은 아직 Legacy/부가 기능 경계에 있다. 이 단계는 그 기능을 실행하거나
제거하지 않는다. 기존 `SimpleRelayV0` 전역 별칭은 adapter 호환을 위한 임시 이름이며 6단계
Legacy 변경 경로 차단 이후에만 제거한다.

## 검증

- `node test_architecture_boundaries_v35.js`: PASS
- `node test_rcc_core_v1.js`: PASS
- `node test_simple_relay_v0.js`: PASS
- `node test_core_shadow_protocol_v3.js`: PASS
- `python -m unittest tests.test_rcc_source_baseline -v`: 17 PASS

## LIVE 효과

없음. 설치본, 확장 reload, Native Host, Chrome 탭, binding, storage, Composer, 메시지 전송을
변경하지 않았다.

## 다음 경계

4단계는 새 Relay 계약과 기존 Browser Adapter를 실제 원문 한 건에 연결하는 별도 LIVE
수락시험이다. 사용자 승인 원문 없이 진행하지 않는다.
