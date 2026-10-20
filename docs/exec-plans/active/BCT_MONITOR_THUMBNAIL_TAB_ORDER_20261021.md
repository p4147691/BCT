# BCT Monitor thumbnail tab order

## Objective

Render a grouped Chrome window badge in the current Chrome tab-strip order.
For example, if the observed ChatGPT tabs are N4, N9, N7 from left to right,
the desktop thumbnail badge is `N4/9/7`, not a numeric `N4/7/9` sort.

## Contract

- RCC projects Chrome `tab.index` as `tabIndex` and observes `tabs.onMoved`.
- BCT exposes only the non-sensitive integer as `tab_index` in Monitor state.
- BWM sorts nodes inside one Chrome window by `tab_index`, with tab ID used
  only as a deterministic fallback when an older RCC does not provide order.
- The thumbnail projection removes duplicate node numbers without re-sorting
  them. Exact `window_id -> HWND` matching and non-ChatGPT filtering stay
  unchanged.
- A coordinated RCC, Core, and Monitor rollout is required before LIVE can
  claim tab-order behavior. Partial deployment must retain the old fallback.

## Verification

- All 25 RCC JavaScript contract tests: PASS
- BCT Monitor runtime tests: 10 PASS
- RCC source baseline tests: 14 PASS
- BWM shell and thumbnail projection checks using N4/N9/N7: PASS
- Relevant Monitor structure, overlay, capture, focus, and deployment checks: PASS
- RCC release candidate inventory verification: PASS
- Python full suite: 879 tests; the only initial failure was the expected
  critical-payload hash guard, updated for this payload and reverified PASS

## Status

`LOCAL_VERIFIED / PR_PENDING / LIVE_NOT_APPLIED`

LIVE RCC, Core, Monitor, Native Host, Chrome tabs, and bindings remain
unchanged. LIVE acceptance requires one coordinated exact-SHA rollout and a
real tab reorder check; a Monitor-only reload cannot prove this contract.
