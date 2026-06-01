from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from app.workflow import (
    ReviewAction,
    WorkflowError,
    allowed_actions,
    apply_action,
    is_active,
    queue_sort_key,
)


DATA_FILE = Path(__file__).resolve().parents[2] / "data" / "review_items.json"


class ActionRequest(BaseModel):
    action: ReviewAction
    reviewer: str = "alex"


app = FastAPI(title="Reviewer Queue API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def load_seed_items() -> list[dict]:
    with DATA_FILE.open() as file:
        return json.load(file)


ITEMS = load_seed_items()


def _serialize(item: dict) -> dict:
    payload = deepcopy(item)
    payload["allowed_actions"] = allowed_actions(item)
    return payload


@app.get("/health")
async def health() -> dict:
    return {"status": "ok"}


@app.post("/dev/reset")
async def reset_items() -> dict:
    global ITEMS
    ITEMS = load_seed_items()
    return {"items": [_serialize(item) for item in ITEMS]}


@app.get("/review-items")
async def list_review_items(active_only: bool = True) -> dict:
    items = [item for item in ITEMS if not active_only or is_active(item)]
    items = sorted(items, key=queue_sort_key)
    return {"items": [_serialize(item) for item in items]}


@app.get("/review-items/{item_id}")
async def get_review_item(item_id: str) -> dict:
    return {"item": _serialize(find_item(item_id))}


@app.post("/review-items/{item_id}/actions")
async def apply_review_action(item_id: str, request: ActionRequest) -> dict:
    item = find_item(item_id)
    try:
        apply_action(item, request.action, request.reviewer)
    except WorkflowError as err:
        raise HTTPException(status_code=409, detail=err.message) from err
    return {"item": _serialize(item)}


def find_item(item_id: str) -> dict:
    for item in ITEMS:
        if item["id"] == item_id:
            return item
    raise HTTPException(status_code=404, detail="Review item not found")
