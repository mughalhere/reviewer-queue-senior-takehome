"""Reviewer queue business rules.

Single source of truth for workflow transitions, queue filtering, and
queue ordering. Kept free of FastAPI / HTTP imports so the rules are
easy to unit test and easy to find.
"""

from __future__ import annotations

from typing import Literal


ReviewAction = Literal["claim", "approve", "reject", "escalate"]
ReviewStatus = Literal["unassigned", "in_review", "approved", "rejected", "escalated"]

TERMINAL_STATUSES: frozenset[str] = frozenset({"approved", "rejected", "escalated"})

_ACTION_TO_TERMINAL: dict[str, str] = {
    "approve": "approved",
    "reject": "rejected",
    "escalate": "escalated",
}

_RISK_RANK: dict[str, int] = {"high": 0, "medium": 1, "low": 2}
_TIER_RANK: dict[str, int] = {"priority": 0, "standard": 1}


class WorkflowError(Exception):
    """Raised when an action is not allowed for an item's current state."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def is_active(item: dict) -> bool:
    return item["status"] not in TERMINAL_STATUSES


def allowed_actions(item: dict) -> list[ReviewAction]:
    status = item["status"]
    if status == "unassigned":
        return ["claim"]
    if status == "in_review":
        return ["approve", "reject", "escalate"]
    return []


def queue_sort_key(item: dict) -> tuple:
    # Higher risk first, priority tier first, then oldest first.
    return (
        _RISK_RANK.get(item["risk_level"], 99),
        _TIER_RANK.get(item["customer_tier"], 99),
        item["submitted_at"],
    )


def apply_action(item: dict, action: ReviewAction, reviewer: str) -> dict:
    """Mutate `item` to reflect `action`, or raise WorkflowError.

    Rules:
      - claim: only from `unassigned` -> `in_review`; records reviewer.
      - approve/reject/escalate: only from `in_review`; reviewer must match
        the assigned reviewer (prevents another reviewer from closing out
        a peer's claim).
      - Any action on a terminal item is rejected.
    """
    status = item["status"]

    if status in TERMINAL_STATUSES:
        raise WorkflowError(
            "terminal",
            f"Item is {status} and cannot accept further actions.",
        )

    if action == "claim":
        if status != "unassigned":
            raise WorkflowError(
                "not_claimable",
                f"Only unassigned items can be claimed (current status: {status}).",
            )
        item["status"] = "in_review"
        item["assigned_reviewer"] = reviewer
        return item

    if action in _ACTION_TO_TERMINAL:
        if status != "in_review":
            raise WorkflowError(
                "not_in_review",
                f"Items must be claimed before they can be {action}d.",
            )
        if item.get("assigned_reviewer") and item["assigned_reviewer"] != reviewer:
            raise WorkflowError(
                "wrong_reviewer",
                f"This item is assigned to {item['assigned_reviewer']}, not {reviewer}.",
            )
        item["status"] = _ACTION_TO_TERMINAL[action]
        return item

    raise WorkflowError("unsupported_action", f"Unsupported action: {action}")
