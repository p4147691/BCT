> **현재 운영 규칙 — 2026-10-30 우선 적용:** [측정 증거·작업 지속 정책](../../MEASUREMENT_EVIDENCE_AND_PROGRESS_POLICY.md) 및 루트 `AGENTS.md`가 이 실행계획의 과거 UNKNOWN/Claim/HOLD 설명보다 우선한다. 측정 결과의 정확성 증거가 없으면 `MEASUREMENT_UNVERIFIED`로 무효 처리하고 그 결과만으로 Claim·작업 중단·재시도 금지를 만들지 않는다. 원인 측정기를 고치면서 다른 진단·개발을 계속한다. 일반 메시지 중복은 수신 노드가 판단하며, 실제 고위험 외부 변경만 정확한 대상과 사용자 승인으로 보호한다. 아래 과거 실행·영수증·시험 서술은 역사로 보존하며 현행 권한 부여 규칙이 아니다.

# BCT Schema 2 Work allowlist (superseded)

This rollout design is preserved as history but is no longer the active
collaboration contract.  Requiring every fresh Work ID in deployed static
configuration created the repeated approval/deploy bottleneck that the final
normalization removes.  See
`BCT_TRUSTED_COLLABORATION_NORMALIZATION_20261017.md`.

## Purpose

Schema 2 remains globally disabled by default and is additionally limited to
explicit Work IDs. This is a rollout safety gate, not an authority grant.
Current Principal, Work ownership, Policy, epoch, lease, attachment, and
dispatcher fences remain authoritative.

## Contract

- `manager_wake_receipt_v2_enabled` defaults to `false`.
- `manager_wake_receipt_v2_allowed_work_ids` defaults to an empty list.
- A new Wake uses Schema 2 only when the global gate is true and its exact
  current Work ID is present. Otherwise it keeps the Schema 1 contract.
- Invalid configuration, an empty runtime allowlist, a removed Work ID, or a
  mismatched Work ID fails closed for every existing Schema 2 processing path.
- The same in-memory, startup-validated allowlist gates Manager polling and
  lease recovery, decision consumption, Worker outbox recovery, Manager wake
  delivery, and the final pre-write fence for RCC pipe sends.
- Stored Wake schema and receipt mode are never rewritten when configuration
  changes. A no-longer-allowed Schema 2 record remains persisted but cannot be
  processed by a restarted Core.
- Existing Schema 1, Issue #111 receipts, UNKNOWN no-resend, Claim, and
  `consumed_at` contracts are unchanged.

## Verification

Focused tests cover default OFF, global ON with an empty/mismatched allowlist,
invalid types and IDs, Core restart, allowlist removal, stale Work fencing,
Manager Poller and decision denial, Dispatcher denial, and both Worker and
Manager final pipe-write fences. The existing PR A/B/C recovery, replay,
takeover, UNKNOWN, attachment, Policy, and lease regressions remain in scope.

## Operational hold

This source change does not authorize Schema 2 activation, LIVE deployment,
Core restart, RCC/Chrome traffic, or reuse of existing UNKNOWN/Claim/Issue #111
records. A new dedicated Work and separate rollout approval are still required.
