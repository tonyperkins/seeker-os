# Seeker OS — Application Lifecycle

**Last updated:** 2026-06-27
**Source:** `seeker_os/events.py`

---

## Overview

Every job in Seeker OS has a lifecycle: discovery → filtering → scoring → review →
application → engagement → outcome. Status changes and lifecycle events are tracked
through an append-only event log. The Kanban board in the UI visualizes this lifecycle
with drag-and-drop status transitions.

---

## Job Statuses

Closed vocabulary — use `JobStatus` constants, not raw strings.

| Status | Description | How it's reached |
|---|---|---|
| `discovered` | Job inserted by pipeline | Pipeline Tier 1 |
| `filtered` | Passed Tier 2 filters | Pipeline Tier 2 |
| `jd_fetched` | Full JD retrieved | Pipeline Tier 3 |
| `duplicate_flagged` | Flagged as duplicate by dedup | Pipeline Tier 3.5 |
| `ready` | Passed scoring threshold | Pipeline Tier 4 |
| `capped` | Per-company cap exceeded | Pipeline Tier 4 |
| `reviewing` | User is reviewing | Manual (UI) |
| `interested` | User marked interest (e.g., resume generated) | Manual or resume generation |
| `rejected` | User rejected with reason | Manual (UI) |
| `skipped` | User skipped | Manual (UI) |
| `applied` | Candidate submitted application | Manual (UI) |
| `engaged` | Company responded, in interview process | Manual (UI) |
| `company_rejected` | Company rejected post-apply | Manual (UI) |
| `withdrawn` | Candidate withdrew post-apply | Manual (UI) |
| `offer_accepted` | Offer accepted | Manual (UI) |
| `offer_declined` | Offer declined | Manual (UI) |

### Status Categories

- **Post-apply:** `applied`, `engaged`, `company_rejected`, `withdrawn`, `offer_accepted`, `offer_declined`
- **Terminal:** `company_rejected`, `withdrawn`, `offer_accepted`, `offer_declined`, `rejected`, `skipped`, `capped`

---

## Event Types

Closed vocabulary — use `EventType` constants, not raw strings.

### Pipeline Events (actor: system)

| Event | When |
|---|---|
| `discovered` | Job inserted by pipeline |
| `filter_passed` | Passed Tier 2 filters |
| `filter_rejected` | Failed Tier 2 filters |
| `jd_fetched` | JD successfully fetched |
| `jd_fetch_failed` | JD fetch failed |
| `jd_fetch_retry` | Retrying previously failed JD fetch |
| `duplicate_flagged` | Content hash dedup match |
| `scored_ready` | Passed scoring threshold |
| `scored_rejected` | Failed scoring (hard reject or below threshold) |
| `capped` | Per-company cap exceeded |

### Manual Events (actor: candidate)

| Event | When |
|---|---|
| `manual_created` | Job manually added |
| `status_changed` | Generic PATCH status change |
| `rejected` | Manual reject with reason |
| `skipped` | Manual skip |
| `overridden` | Rejection overridden |
| `resume_generated` | Resume generated, status → interested |
| `applied` | Candidate submitted application |
| `withdrawn` | Candidate withdrew (post-apply) |
| `offer_accepted` | Offer accepted |
| `offer_declined` | Offer declined |

### Company Events (actor: company)

| Event | When |
|---|---|
| `company_rejected` | Company rejected (post-apply) |

### Engaged Sub-lifecycle Events

These events do **NOT** change status — they are logged while the job remains `engaged`.

| Event | When |
|---|---|
| `engaged` | Moved to engaged sub-lifecycle (status change) |
| `interview` | Interview scheduled |
| `challenge_assigned` | Take-home challenge assigned |
| `challenge_submitted` | Challenge submitted |
| `offer_received` | Offer received |
| `offer_countered` | Offer countered |
| `followup_sent` | Follow-up sent (resets staleness) |
| `contact_received` | Company contact received (resets staleness) |

---

## Actors

Closed vocabulary — exactly three values:

| Actor | Who |
|---|---|
| `candidate` | The user (job seeker) |
| `company` | The employer |
| `system` | The pipeline / automated process |

---

## Transition Rules

### `transition_status()`

The **ONLY** way a status change should happen. It updates `jobs.status` AND inserts
an `application_events` row in the same transaction.

```python
transition_status(
    db, job_id, new_status, event_type, actor,
    *, metadata=None, occurred_at=None, note=None,
    extra_sets=None,  # additional column updates (e.g., {"score": 8.5})
    allow_before_discovery=False,  # for clean-start backdated events
)
```

### `record_event()`

The **ONLY** way events are written (called by `transition_status` and directly for
engaged sub-lifecycle events that don't change status).

### Validation

- `event_type` must be in `EventType._ALL` (warns on unknown, does not raise)
- `actor` must be in `Actor._ALL` (raises `ValueError` on invalid)
- `occurred_at` cannot be in the future
- `occurred_at` cannot be before job's `discovered_at` (unless `allow_before_discovery=True`)

---

## Stale Tracking

Applied and engaged jobs are tracked for staleness — if no activity has occurred
recently, the job is flagged as stale in the UI.

### `compute_stale_flag()`

```python
is_stale, days_since = compute_stale_flag(db, job_id, status, stale_after_days)
```

- Only applies to `applied` and `engaged` statuses
- Checks the most recent event from `STALE_ACTIVITY_EVENTS` allowlist
- Returns `(is_stale: bool, days_since_last_activity: int | None)`
- **Not stored** — computed on-demand, not an event

### Stale Activity Events (reset staleness clock)

| Event |
|---|
| `applied` |
| `engaged` |
| `interview` |
| `challenge_assigned` |
| `challenge_submitted` |
| `offer_received` |
| `offer_countered` |
| `followup_sent` |
| `contact_received` |

Terminal-status events (`company_rejected`, `withdrawn`, `offer_accepted`,
`offer_declined`) are excluded — the status guard short-circuits before stale computes.
New event types default to NOT resetting staleness unless explicitly added to the allowlist.

---

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `PATCH` | `/api/jobs/{job_id}` | Generic status update (status_changed event) |
| `POST` | `/api/jobs/{job_id}/reject` | Reject with reason |
| `POST` | `/api/jobs/{job_id}/skip` | Skip |
| `POST` | `/api/jobs/{job_id}/override` | Override a rejection |
| `POST` | `/api/jobs/{job_id}/apply` | Mark as applied |
| `POST` | `/api/jobs/{job_id}/transition` | Post-apply transition (company_rejected, withdrawn, engaged, offer_accepted, offer_declined) |
| `POST` | `/api/jobs/{job_id}/engaged-events` | Log engaged sub-lifecycle event (no status change) |
| `POST` | `/api/jobs/{job_id}/clean-start` | Enter at post-apply status with backdated event |
| `GET` | `/api/jobs/{job_id}/events` | Get event timeline |
| `POST` | `/api/jobs/{job_id}/events` | Add custom event |

---

## Kanban Board

The frontend Kanban board (`/kanban`) visualizes the application lifecycle with
drag-and-drop columns. Each column maps to a job status:

| Column | Status |
|---|---|
| Ready | `ready` |
| Reviewing | `reviewing` |
| Interested | `interested` |
| Applied | `applied` |
| Engaged | `engaged` |
| Rejected | `rejected` |
| Company Rejected | `company_rejected` |
| Withdrawn | `withdrawn` |
| Offer Accepted | `offer_accepted` |
| Offer Declined | `offer_declined` |

Dragging a job between columns triggers a `PATCH /api/jobs/{job_id}` or
`POST /api/jobs/{job_id}/transition` call, which routes through `transition_status()`
and records the appropriate event.

---

## Clean Start

The `clean-start` endpoint allows entering a job directly at a post-apply status
(e.g., `applied` or `engaged`) with a backdated event. This is useful for importing
jobs that were applied to before being added to Seeker OS.

- Uses `allow_before_discovery=True` to bypass the discovery-date floor check
- Still validates that `occurred_at` is not in the future
- Records the event with the user-specified `occurred_at` timestamp
