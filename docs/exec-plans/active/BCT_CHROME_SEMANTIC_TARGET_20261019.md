# BCT Chrome semantic target — 2026-10-19

Status: IMPLEMENTING.

## Goal

Extend `desktop_application_target` so an MCP caller can list or uniquely bind
an existing Chrome window by optional window title, profile label and active or
any tab title. VTL Desktop Session Agent 1.8 owns read-only UI Automation; BCT
owns strict response validation, selector validation and the exact Lease.

## Contract

- `profile_query`: case-insensitive substring, at most 200 characters.
- `tab_title_query`: case-insensitive substring, at most 500 characters.
- `tab_scope`: `active` (default) or `any`.
- No URL is returned or used as a selector.
- Explorer rejects Chrome selectors; Chrome rejects `folder_path`.
- Chrome bind fails closed on unavailable/incomplete inspection, zero matches,
  multiple matches or any truncated inventory.
- List is read-only. Bind acquires a Lease but does not activate, focus, launch,
  close or send input to Chrome.

## Completion route

1. Add Agent command transport and strict response-shape validation.
2. Add feature selector validation, list output and fail-closed binding.
3. Run focused tests, then the safe local regression suite.
4. Merge only after CI succeeds; deploy the exact main release.
5. Run authenticated LIVE list and exact bind/release while checking pre-existing
   Chrome PID/process-birth and HWND identity before/after.
6. Record immutable SHAs and move this plan to `completed/`.
