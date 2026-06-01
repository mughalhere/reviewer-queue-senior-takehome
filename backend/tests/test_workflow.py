from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import main
from app.workflow import (
    WorkflowError,
    allowed_actions,
    apply_action,
    is_active,
    queue_sort_key,
)


def make_item(**overrides) -> dict:
    base = {
        "id": "RV-TEST",
        "title": "test item",
        "submitted_at": "2026-04-01T00:00:00Z",
        "risk_level": "medium",
        "customer_tier": "standard",
        "status": "unassigned",
        "assigned_reviewer": None,
        "notes_count": 0,
        "summary": "",
    }
    base.update(overrides)
    return base


# ----- transition rules ---------------------------------------------------


def test_claim_moves_unassigned_to_in_review_and_records_reviewer():
    item = make_item(status="unassigned")
    apply_action(item, "claim", "alex")
    assert item["status"] == "in_review"
    assert item["assigned_reviewer"] == "alex"


def test_claim_rejected_when_already_in_review():
    item = make_item(status="in_review", assigned_reviewer="sam")
    with pytest.raises(WorkflowError) as exc:
        apply_action(item, "claim", "alex")
    assert exc.value.code == "not_claimable"
    # state is unchanged
    assert item["assigned_reviewer"] == "sam"


@pytest.mark.parametrize("terminal", ["approved", "rejected", "escalated"])
def test_claim_rejected_when_terminal(terminal):
    item = make_item(status=terminal, assigned_reviewer="sam")
    with pytest.raises(WorkflowError) as exc:
        apply_action(item, "claim", "alex")
    assert exc.value.code == "terminal"


@pytest.mark.parametrize(
    "action,expected", [("approve", "approved"), ("reject", "rejected"), ("escalate", "escalated")]
)
def test_terminal_actions_from_in_review(action, expected):
    item = make_item(status="in_review", assigned_reviewer="alex")
    apply_action(item, action, "alex")
    assert item["status"] == expected


@pytest.mark.parametrize("action", ["approve", "reject", "escalate"])
def test_terminal_actions_rejected_when_unassigned(action):
    item = make_item(status="unassigned")
    with pytest.raises(WorkflowError) as exc:
        apply_action(item, action, "alex")
    assert exc.value.code == "not_in_review"
    assert item["status"] == "unassigned"


@pytest.mark.parametrize("terminal", ["approved", "rejected", "escalated"])
@pytest.mark.parametrize("action", ["approve", "reject", "escalate"])
def test_terminal_items_reject_every_action(terminal, action):
    item = make_item(status=terminal, assigned_reviewer="alex")
    with pytest.raises(WorkflowError) as exc:
        apply_action(item, action, "alex")
    assert exc.value.code == "terminal"
    assert item["status"] == terminal


def test_terminal_action_rejected_when_reviewer_does_not_match_assignee():
    item = make_item(status="in_review", assigned_reviewer="sam")
    with pytest.raises(WorkflowError) as exc:
        apply_action(item, "approve", "alex")
    assert exc.value.code == "wrong_reviewer"
    assert item["status"] == "in_review"


# ----- active filter + sort ----------------------------------------------


@pytest.mark.parametrize("status", ["unassigned", "in_review"])
def test_active_includes_non_terminal(status):
    assert is_active(make_item(status=status)) is True


@pytest.mark.parametrize("status", ["approved", "rejected", "escalated"])
def test_active_excludes_terminal(status):
    assert is_active(make_item(status=status)) is False


def test_queue_sort_orders_by_risk_then_tier_then_age():
    high_priority_old = make_item(
        id="A", risk_level="high", customer_tier="priority", submitted_at="2026-04-01T00:00:00Z"
    )
    high_priority_new = make_item(
        id="B", risk_level="high", customer_tier="priority", submitted_at="2026-04-02T00:00:00Z"
    )
    high_standard = make_item(
        id="C", risk_level="high", customer_tier="standard", submitted_at="2026-03-30T00:00:00Z"
    )
    medium_priority = make_item(
        id="D", risk_level="medium", customer_tier="priority", submitted_at="2026-03-29T00:00:00Z"
    )
    low_standard = make_item(
        id="E", risk_level="low", customer_tier="standard", submitted_at="2026-03-28T00:00:00Z"
    )

    items = [low_standard, medium_priority, high_standard, high_priority_new, high_priority_old]
    ordered = sorted(items, key=queue_sort_key)
    assert [it["id"] for it in ordered] == ["A", "B", "C", "D", "E"]


# ----- allowed_actions ---------------------------------------------------


def test_allowed_actions_for_unassigned():
    assert allowed_actions(make_item(status="unassigned")) == ["claim"]


def test_allowed_actions_for_in_review():
    assert allowed_actions(make_item(status="in_review")) == ["approve", "reject", "escalate"]


@pytest.mark.parametrize("terminal", ["approved", "rejected", "escalated"])
def test_allowed_actions_for_terminal(terminal):
    assert allowed_actions(make_item(status=terminal)) == []


# ----- HTTP layer (thin integration) -------------------------------------


@pytest.fixture
def client():
    main.ITEMS = main.load_seed_items()
    return TestClient(main.app)


def test_list_review_items_excludes_terminal_and_orders_by_urgency(client):
    response = client.get("/review-items")
    assert response.status_code == 200
    items = response.json()["items"]

    statuses = {it["status"] for it in items}
    assert statuses.isdisjoint({"approved", "rejected", "escalated"})

    # top of queue must be highest urgency: high risk, priority tier, oldest
    top = items[0]
    assert top["risk_level"] == "high"
    assert top["customer_tier"] == "priority"


def test_list_review_items_includes_allowed_actions(client):
    response = client.get("/review-items")
    items = response.json()["items"]
    for item in items:
        assert "allowed_actions" in item
        if item["status"] == "unassigned":
            assert item["allowed_actions"] == ["claim"]


def test_apply_action_returns_409_on_invalid_transition(client):
    # RV-1033 is escalated (terminal) in seed data
    response = client.post(
        "/review-items/RV-1033/actions",
        json={"action": "claim", "reviewer": "alex"},
    )
    assert response.status_code == 409
    assert "cannot" in response.json()["detail"].lower()


def test_apply_action_full_happy_path(client):
    # RV-1024 starts unassigned
    claim = client.post(
        "/review-items/RV-1024/actions",
        json={"action": "claim", "reviewer": "alex"},
    )
    assert claim.status_code == 200
    item = claim.json()["item"]
    assert item["status"] == "in_review"
    assert item["assigned_reviewer"] == "alex"
    assert set(item["allowed_actions"]) == {"approve", "reject", "escalate"}

    approve = client.post(
        "/review-items/RV-1024/actions",
        json={"action": "approve", "reviewer": "alex"},
    )
    assert approve.status_code == 200
    assert approve.json()["item"]["status"] == "approved"
    assert approve.json()["item"]["allowed_actions"] == []


def test_unknown_item_returns_404(client):
    response = client.get("/review-items/NOPE")
    assert response.status_code == 404
