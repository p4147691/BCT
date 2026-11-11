"""Pure Chain Recipe stage descriptions and progress values."""
from __future__ import annotations

from typing import Any



def chain_recipe_outline() -> list[dict[str, Any]]:
    """One visible, non-executing map of the Chain Recipe's fixed composition."""
    return [
        {"number": 0, "name": "Input R", "kind": "partial_recipe"},
        {"number": 1, "name": "State R", "kind": "partial_recipe"},
        {"number": 2, "name": "Write Direction R", "kind": "partial_recipe"},
        {"number": 3, "name": "Save Direction R", "kind": "partial_recipe"},
        {
            "number": 4,
            "name": "Recover Node R",
            "kind": "partial_recipe",
            "optional": True,
            "effect": "runs only when A saved node_recovery with one exact node UUID; Check Node R then rereads State R",
        },
        {"number": 5, "name": "Prepare Send Direction R", "kind": "partial_recipe"},
        {
            "number": 6,
            "name": "Apply Conversation Network R",
            "kind": "partial_recipe",
            "effect": "applies only declared network updates; otherwise rechecks the current route",
        },
        {
            "number": 7,
            "name": "Send Direction R",
            "kind": "partial_recipe",
            "contains": [
                {"name": "Check Chain Work", "kind": "block", "effect": "advisory observation only"},
                {"name": "Read Saved Direction", "kind": "block"},
                {"name": "Send Delayed Message", "kind": "block", "effect": "prearms the response Watch"},
                {"name": "Send Direction Message", "kind": "block"},
            ],
            "after_response": {
                "name": "Watch·Alarm Continuation R",
                "kind": "partial_recipe",
                "contains": [
                    {"name": "Watch Alarm R", "kind": "partial_recipe"},
                    {
                        "name": "Continuation R",
                        "kind": "partial_recipe",
                        "contains": [
                            {"name": "Interpret Next Task", "kind": "block"},
                            {"name": "SELF / MANAGER follow-up", "kind": "branch"},
                        ],
                    },
                ],
            },
        },
    ]


def chain_recipe_progress(*, completed_through: int, next_number: int | None) -> dict[str, Any]:
    """Describe recipe progress only; it never executes or selects a step."""
    outline = chain_recipe_outline()
    return {
        "completed": [stage for stage in outline if stage["number"] <= completed_through],
        "next": next((stage for stage in outline if stage["number"] == next_number), None),
    }
