# Submission

## Summary of changes

- Extracted the reviewer workflow into a pure `backend/app/workflow.py` module (transitions, terminal-state guard, queue filter, queue sort, allowed-actions lookup). The HTTP layer in `main.py` is now a thin shell over it.
- Fixed every workflow-correctness bug listed in the brief: claim now requires `unassigned`, terminal actions require `in_review`, all three terminal states block further actions, the active queue excludes all three terminals, and the queue is ordered by `risk_level → customer_tier → age` as specified.
- Frontend reads `allowed_actions` from the API and renders buttons accordingly, so invalid actions are visibly disabled with a tooltip instead of triggering an opaque 409.
- Specific server error messages now surface to the reviewer instead of the previous generic "could not be completed".
- Added 37 backend tests covering transitions, queue ordering, the active filter, `allowed_actions`, and the HTTP→workflow mapping. The 2 original smoke tests still pass.

## Bugs fixed

| File:line (pre) | Bug | Fix |
|---|---|---|
| `backend/app/main.py:59` | Active queue only filtered `approved`; `rejected` and `escalated` leaked in. | `workflow.is_active()` excludes all three terminal statuses. |
| `backend/app/main.py:61` | Queue sorted by `submitted_at` desc — ignored urgency entirely. | `workflow.queue_sort_key()` orders by `(risk_rank, tier_rank, submitted_at asc)`. |
| `backend/app/main.py:75-77` | `claim` was allowed on `in_review` items, letting a second reviewer overwrite an existing assignment. | `workflow.apply_action` only allows `claim` from `unassigned`. |
| `backend/app/main.py:80-83` | `approve`/`reject`/`escalate` were allowed from `unassigned` and from `rejected`/`escalated`. Only `approved` was guarded. | All three terminal actions require `in_review`; terminal items reject every action with a specific message. |
| `backend/app/main.py:80-83` | A reviewer could close out another reviewer's claim. | Terminal actions require `reviewer == assigned_reviewer`; returns a clear "assigned to X, not Y" error. |
| `frontend/src/api.ts:47` | Frontend swallowed the server's `detail` and showed a generic "Action failed". | `ApiError` carries the parsed `detail`; the banner displays it. |
| `frontend/src/App.vue` (all four buttons) | All actions were always enabled regardless of status. | Buttons read `selectedItem.allowed_actions`; invalid actions are `disabled` with a `title` tooltip explaining why. |

## Product/UX decisions

**The deliberate UX improvement: server-driven contextual actions + visible urgency.**

Problem I saw: a reviewer hitting this app couldn't answer the four questions in the brief. The queue was ordered by submission date, not urgency, so "what do I work on next?" required scanning every row. All four action buttons were always enabled, so "what can I do on this item?" was answered by clicking and reading an opaque error. Status was a small grey label and risk/tier were buried in meta text, so "what's the urgency?" required reading prose.

What I changed and why:

1. **Risk pill + priority star in every queue row.** Now the top of the queue visibly reads "HIGH · ★ Priority" and the eye can find work without parsing dates.
2. **`allowed_actions` returned per item from the backend.** The frontend disables buttons that aren't valid for the current status and shows the reason in the tooltip. Single source of truth lives in `workflow.py`; the frontend doesn't replicate the state machine.
3. **"Mine" tag** on items assigned to the current reviewer (Alex), plus a left-border highlight in the queue. Answers "who owns this?" at a glance.
4. **Specific error messages** from the server are surfaced in the banner ("This item is assigned to sam, not alex.") instead of generic copy.
5. **Terminal note** under the action row when an item has no allowed actions, so the empty button strip isn't confusing.

**Tradeoff I made:** I chose to express `allowed_actions` server-side rather than recomputing it in the frontend. This costs one extra field in the GET response, but it keeps the rules in one place and means a future second client (mobile, CLI) gets the same affordances for free. The alternative — duplicating the small lookup in TypeScript — would be slightly faster to render but invites the two implementations to drift, which is precisely the kind of bug the original codebase had (terminal filter logic was nearly-but-not-quite right).

**What I deliberately did not do in the timebox:** no toast/snackbar library, no animations on item removal, no front-end test framework (vitest isn't in the project's dependencies and adding the toolchain would have cost ~10 minutes that I spent on backend test depth instead).

## Tests added

`backend/tests/test_workflow.py` (37 cases, all green; smoke tests still pass; total 39/39):

Unit tests against `workflow.apply_action` / `is_active` / `queue_sort_key` / `allowed_actions`:

- `claim` succeeds from `unassigned` and records the reviewer.
- `claim` is rejected when status is `in_review` (state unchanged).
- `claim` is rejected on every terminal status (parametrized).
- `approve`/`reject`/`escalate` succeed from `in_review` to the expected terminal (parametrized).
- `approve`/`reject`/`escalate` are rejected when status is `unassigned`.
- Every action × every terminal status is rejected (3 × 3 parametrized matrix).
- A reviewer different from the assignee cannot close out the claim.
- `is_active` returns true for `unassigned`/`in_review`, false for all three terminals.
- `queue_sort_key` produces the exact specified order across a mixed fixture.
- `allowed_actions` returns `["claim"]` for unassigned, the three terminal actions for in_review, and `[]` for every terminal.

Thin HTTP integration tests via `TestClient`:

- `GET /review-items` excludes terminal items and returns the highest-urgency item first.
- `GET /review-items` includes `allowed_actions` on every payload.
- `POST /review-items/{id}/actions` returns 409 with a non-empty `detail` on an invalid transition (verified against the escalated seed item RV-1033).
- Full happy path: claim → approve on RV-1024 returns 200 at each step with the right `status` and `allowed_actions`.
- `GET /review-items/{unknown}` returns 404.

End-to-end manual verification I ran against `uvicorn`:

- Confirmed queue order: RV-1024 (high/priority/2026-04-02) at the top, then RV-1030 (high/priority, newer), then high/standard pair, then medium tiers, then low. Approved/rejected/escalated items absent.
- Confirmed 409 with specific message on: claiming an in-review item, approving an unassigned item, a wrong-reviewer approve, and approving an already-approved item.

## Known gaps

- **Persistence**: items live in process memory. `/dev/reset` reloads the seed data; restarting `uvicorn` does the same. Out of scope per the brief.
- **Authentication**: reviewer identity is still hardcoded as `alex` in the frontend and accepted verbatim by the backend. The brief says to hardcode it for this exercise; in production this would come from an auth layer and the wrong-reviewer guard would enforce real identity.
- **Frontend tests**: no test framework is configured in `package.json` (only `vite`, `vue-tsc`, `typescript`). I prioritized depth of backend coverage over installing vitest. Adding `vitest + @vue/test-utils` and writing a few component tests against `App.vue` is the obvious next step.
- **Notes feature**: `notes_count` is displayed but there is no notes endpoint or UI. Out of scope.
- **Pagination / search / filter**: not needed for a 12-item demo queue, but a real queue would need at least a "mine only" filter, free-text search on title, and date pagination.
- **Optimistic updates**: actions wait for the server roundtrip. Acceptable here; would matter at scale.
- **Concurrent claims**: the wrong-reviewer guard catches the common race, but the in-memory store isn't transactionally safe across requests. A real persistence layer would handle this with row-level locking or optimistic concurrency.

## Files changed and why

- `backend/app/workflow.py` (new) — single source of truth for transitions, terminal-state set, queue filter/sort, and `allowed_actions`. Kept free of FastAPI imports so it's trivially unit-testable.
- `backend/app/main.py` — reduced to HTTP wiring: it loads the seed file, finds items, delegates to `workflow.apply_action`, and maps `WorkflowError` to HTTP 409 with the workflow's own message. Now also serializes `allowed_actions` onto every item response.
- `backend/tests/test_workflow.py` (new) — 37 tests covering every transition + the queue rules + the HTTP error mapping.
- `backend/requirements.txt` — added `httpx==0.28.1`, required by `fastapi.testclient.TestClient`.
- `frontend/src/api.ts` — added `allowed_actions` to the `ReviewItem` type; introduced `ApiError` so the UI can read the server's `detail` instead of throwing a generic Error.
- `frontend/src/App.vue` — render buttons from `allowed_actions` (disabled + tooltip when not allowed); risk pill, priority star, and "mine" tag in queue rows; surfaced server error message; removed terminal items from the local list after a terminal action so the active view stays correct without a refetch.
- `frontend/src/styles.css` — styles for the risk pills, the priority/mine tags, the per-status status pill colors, the terminal note, and the highlighted primary "Claim" button.
- `SUBMISSION.md` (new) — this file.

The `TAKEHOME:` comment convention was deliberately not used — every decision is documented here in one place rather than scattered across the code.

## AI assistance used

I used Claude (Opus 4.7, via Claude Code) throughout this exercise. Concretely:

- **Exploration**: I had Claude run parallel read-only sweeps of the backend, frontend, and top-level config to produce a single map of the codebase, the existing workflow logic, and the seed data. I read the actual `main.py` and `App.vue` myself afterward to verify the report.
- **Planning**: I wrote the implementation plan (ordering of fixes, scope cuts, file layout) before writing code, and used Claude as a sanity check on the priority order. The plan file lives at `~/.claude/plans/timebox-a-strong-senior-happy-backus.md` in my local Claude Code workspace.
- **Code drafts**: `workflow.py`, the tests, the Vue changes, and this SUBMISSION.md were drafted with Claude and then read line-by-line. I verified them by (1) running the pytest suite, (2) running `vue-tsc --noEmit`, and (3) hitting the running API with `curl` to confirm the queue order, 409 messages, and happy-path transitions matched my expectations.
- **Review**: I deliberately did not let the model add features beyond the plan. The wrong-reviewer guard is the one rule I added that wasn't in the brief's bullet list; I included it because the brief says "invalid actions should be rejected cleanly" and a peer reviewer overwriting your claim is exactly that kind of invalid action.

Anything in this repo I would defend in a review: the workflow module's transition table, the test coverage, the choice to express `allowed_actions` server-side. Anything I'd flag as judgment calls open to debate: surfacing raw server error strings to end users (fine for an internal tool, would want a translation layer for a customer-facing one), and removing terminal items from the local list rather than refetching (fast and consistent here, but a refetch would be safer if multiple reviewers were acting concurrently).
