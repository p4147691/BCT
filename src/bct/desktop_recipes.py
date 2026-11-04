"""Readable BDC component catalogue and safe composition recipes.

This module plans which existing public BCT capabilities to use.  It never
acquires a lease, performs an effect, or hides child Operation receipts.
"""
from __future__ import annotations

from typing import Any


_PRIMITIVES: tuple[dict[str, str], ...] = (
    {"capability": "desktop_session_status", "category": "observe", "effect": "read"},
    {"capability": "desktop_capture", "category": "observe", "effect": "read"},
    {"capability": "desktop_explore", "category": "observe", "effect": "read"},
    {"capability": "desktop_window_list", "category": "observe", "effect": "read"},
    {"capability": "desktop_application_target", "category": "target", "effect": "read-or-lease"},
    {"capability": "desktop_control_lease", "category": "lease", "effect": "state"},
    {"capability": "desktop_window_activate", "category": "window", "effect": "desktop"},
    {"capability": "desktop_window_manage", "category": "window", "effect": "desktop"},
    {"capability": "desktop_window_activate_reconcile", "category": "recovery", "effect": "read"},
    {"capability": "desktop_uia_elements_list", "category": "native-ui", "effect": "read"},
    {"capability": "desktop_uia_element_action", "category": "native-ui", "effect": "desktop"},
    {"capability": "desktop_chrome_content_list", "category": "chrome-ui", "effect": "read"},
    {"capability": "desktop_chrome_content_action", "category": "chrome-ui", "effect": "desktop"},
    {"capability": "desktop_chrome_tab_select", "category": "chrome-ui", "effect": "desktop"},
    {"capability": "desktop_chrome_tab_reconcile", "category": "recovery", "effect": "read"},
    {"capability": "desktop_input", "category": "session-io", "effect": "desktop"},
    {"capability": "desktop_clipboard", "category": "session-io", "effect": "read-or-desktop"},
    {"capability": "desktop_program_launch", "category": "launch", "effect": "process"},
    {"capability": "desktop_emergency_stop", "category": "safety", "effect": "state"},
)


_COMPONENT_GROUPS: tuple[dict[str, Any], ...] = (
    {
        "id": "bdc.observe",
        "kind": "module",
        "purpose": "Observe the current Windows session without changing it.",
        "capabilities": [
            "desktop_session_status", "desktop_capture", "desktop_explore",
            "desktop_window_list",
        ],
    },
    {
        "id": "bdc.target_and_lease",
        "kind": "module",
        "purpose": "Resolve one exact desktop target and fence control with a lease.",
        "capabilities": ["desktop_application_target", "desktop_control_lease"],
    },
    {
        "id": "bdc.window_control",
        "kind": "module",
        "purpose": "Activate or arrange only the exact leased window.",
        "capabilities": [
            "desktop_window_activate", "desktop_window_manage",
            "desktop_window_activate_reconcile",
        ],
    },
    {
        "id": "bdc.native_ui",
        "kind": "module",
        "purpose": "Inspect and operate exact Windows UI Automation elements.",
        "capabilities": ["desktop_uia_elements_list", "desktop_uia_element_action"],
    },
    {
        "id": "bdc.chrome_ui",
        "kind": "module",
        "purpose": "Inspect and operate an exact existing Chrome window without arbitrary code.",
        "capabilities": [
            "desktop_chrome_content_list", "desktop_chrome_content_action",
            "desktop_chrome_tab_select", "desktop_chrome_tab_reconcile",
        ],
    },
    {
        "id": "bdc.session_io",
        "kind": "module",
        "purpose": "Perform bounded input or clipboard effects under the active session lease.",
        "capabilities": ["desktop_input", "desktop_clipboard"],
    },
    {
        "id": "bdc.open_and_launch",
        "kind": "module",
        "purpose": "Open an exact folder or launch an exact executable with identity evidence.",
        "capabilities": ["desktop_explorer_folder_open", "desktop_program_launch"],
    },
    {
        "id": "bdc.stop_control",
        "kind": "primitive",
        "purpose": "Latch emergency stop and revoke the active desktop control lease.",
        "capabilities": ["desktop_emergency_stop"],
    },
)


_RECIPES: dict[str, dict[str, Any]] = {
    "inspect_desktop": {
        "kind": "full_recipe",
        "purpose": "Understand the visible desktop before choosing any effect.",
        "steps": [
            ("desktop_session_status", "Confirm the exact interactive session and monitors."),
            ("desktop_window_list", "List exact visible HWND and process fingerprints."),
            ("desktop_capture", "Capture only the screen, monitor, or HWND needed for visual proof."),
        ],
        "completion": "Current session, candidate windows, and visual evidence are explicit.",
    },
    "use_application": {
        "kind": "partial_recipe",
        "purpose": "Use one exact supported Chrome or Explorer window via fresh native UIA evidence.",
        "target_scope": "CHROME_OR_EXPLORER_ONLY",
        "steps": [
            ("desktop_application_target", "Bind one exact Chrome or Explorer target and acquire its window lease; reject other applications."),
            ("desktop_window_activate", "Explicitly activate the leased window when the action requires foreground."),
            ("desktop_uia_elements_list", "Read fresh actionable element metadata."),
            ("desktop_uia_element_action", "Apply one exact fresh element action."),
            ("desktop_uia_elements_list", "Independently re-observe the target element; if its effect cannot be proven, report UNVERIFIED."),
            ("desktop_control_lease", "Release the lease even when readback fails; never retry UNKNOWN."),
        ],
        "decision_points": ["Choose one fresh element from the read-only list.", "Stop on UNKNOWN; never resend with a new operation ID."],
    },
    "use_chrome": {
        "kind": "partial_recipe",
        "purpose": "Use an existing Chrome window through bounded official desktop/UI contracts.",
        "steps": [
            ("desktop_application_target", "Bind exactly one Chrome window by stable observed identity."),
            ("desktop_window_activate", "Activate explicitly only when the selected action requires it."),
            ("desktop_chrome_content_list", "List fresh bounded page elements without reading values."),
            ("desktop_chrome_content_action", "Set or invoke one exact fresh page element."),
            ("desktop_chrome_content_list", "Independently inspect fresh page metadata; this does not prove changed values, so report UNVERIFIED without stronger evidence."),
            ("desktop_control_lease", "Release the lease; never retry UNKNOWN."),
        ],
        "alternatives": ["desktop_chrome_tab_select selects a proven existing tab; it never opens or navigates."],
        "decision_points": ["Prefer CDP or a dedicated Chrome API when it provides the required operation.", "Stop on UNKNOWN and use the matching reconcile primitive only when its proof contract is satisfied."],
    },
    "arrange_window": {
        "kind": "partial_recipe",
        "purpose": "Restore, minimize, maximize, move, or resize one exact Chrome or Explorer window.",
        "target_scope": "CHROME_OR_EXPLORER_ONLY",
        "steps": [
            ("desktop_window_list", "Read the current exact window fingerprint."),
            ("desktop_application_target", "Acquire an exact Chrome or Explorer window lease; reject unsupported windows."),
            ("desktop_window_manage", "Apply one bounded geometry/state change."),
            ("desktop_window_list", "Independently re-observe exact HWND and requested state; if unavailable report UNVERIFIED."),
            ("desktop_control_lease", "Release the lease after readback; do not retry UNKNOWN."),
        ],
        "completion": "The target fingerprint still matches and the requested state is independently observed.",
    },
    "launch_program": {
        "kind": "partial_recipe",
        "purpose": "Launch one exact executable and bind only its newly created visible window.",
        "steps": [
            ("desktop_control_lease", "Acquire the current-session lease."),
            ("desktop_program_launch", "Launch the exact absolute executable and record PID identity."),
            ("desktop_window_list", "Independently verify new PID and visible window identity; report UNVERIFIED if absent."),
            ("desktop_control_lease", "Release after readback or failure; never repeat an UNKNOWN launch."),
        ],
        "completion": "The exact new PID/window identity is proven; no pre-existing window is substituted.",
    },
    "open_folder": {
        "kind": "full_recipe",
        "purpose": "Open one exact existing absolute folder in Explorer.",
        "steps": [("desktop_explorer_folder_open", "Use the existing complete open/reconcile/optional-activate/release recipe.")],
        "completion": "An Explorer window for the exact folder is reconciled and control is released.",
    },
}


def desktop_catalogue() -> dict[str, Any]:
    """Return a stable user-facing map of existing BDC building blocks."""
    return {
        "status": "OK",
        "schema": "bct.desktop-recipes.v1",
        "execution": "PLAN_ONLY",
        "primitives": [dict(item, kind="primitive") for item in _PRIMITIVES],
        "modules": [dict(item) for item in _COMPONENT_GROUPS],
        "recipes": [
            {"name": name, "kind": item["kind"], "purpose": item["purpose"], **({"target_scope": item["target_scope"]} if "target_scope" in item else {})}
            for name, item in _RECIPES.items()
        ],
        "safety": [
            "Every effect keeps its own Work-scoped Operation receipt.",
            "Acquire an exact target and lease before effects; release after readback.",
            "UNKNOWN effects are reconciled, never repeated under a new operation ID.",
            "Use desktop_emergency_stop independently whenever control must stop immediately.",
        ],
    }


def plan_desktop_recipe(recipe: str) -> dict[str, Any]:
    """Return ordered existing capabilities for one named BDC recipe."""
    name = str(recipe or "").strip().casefold()
    selected = _RECIPES.get(name)
    if selected is None:
        return {
            "status": "INVALID_REQUEST",
            "reason": "BDC_RECIPE_UNKNOWN",
            "available_recipes": sorted(_RECIPES),
        }
    value = {key: val for key, val in selected.items() if key != "steps"}
    value.update({
        "status": "OK",
        "schema": "bct.desktop-recipe-plan.v1",
        "execution": "PLAN_ONLY",
        "recipe": name,
        "steps": [
            {"order": index, "capability": capability, "purpose": purpose}
            for index, (capability, purpose) in enumerate(selected["steps"], start=1)
        ],
        "next": "Execute each selected capability through its public BCT tool with a unique exact operation_id.",
    })
    return value
