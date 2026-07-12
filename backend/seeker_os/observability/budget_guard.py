"""Budget guard for paid retrieval calls.

Checks daily/monthly call counts against caps defined in observability.yml
before allowing a paid Tavily search. Records each call (success or failure)
in the retrieval_calls table for counting and reporting.

When a cap is exceeded, the guard returns False and the caller returns empty
results with a WARNING log — the pipeline degrades gracefully.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from seeker_os.database import get_connection

logger = logging.getLogger(__name__)


def _today_bounds() -> tuple[str, str]:
    """Return (start, end) ISO timestamps for the current UTC day."""
    now = datetime.now(UTC)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start.replace(hour=23, minute=59, second=59)
    return start.isoformat(), end.isoformat()


def _month_bounds() -> tuple[str, str]:
    """Return (start, end) ISO timestamps for the current UTC month."""
    now = datetime.now(UTC)
    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    if now.month == 12:
        end = start.replace(year=now.year + 1, month=1)  # type: ignore[arg-type]
    else:
        end = start.replace(month=now.month + 1)  # type: ignore[arg-type]
    end = end.replace(second=59, microsecond=999999)
    return start.isoformat(), end.isoformat()


def check_budget(adapter_type: str, daily_cap: int, monthly_cap: int) -> bool:
    """Return True if the call is within budget, False if a cap is exceeded.

    A cap of 0 means unlimited (always allowed).
    """
    if daily_cap == 0 and monthly_cap == 0:
        return True

    db = get_connection()
    try:
        if daily_cap > 0:
            day_start, day_end = _today_bounds()
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM retrieval_calls "
                "WHERE adapter_type = ? AND called_at >= ? AND called_at <= ?",
                (adapter_type, day_start, day_end),
            ).fetchone()
            if row and row["cnt"] >= daily_cap:
                logger.warning(
                    "budget_cap_exceeded: %s daily cap %d reached (%d calls today)",
                    adapter_type, daily_cap, row["cnt"],
                )
                return False

        if monthly_cap > 0:
            month_start, month_end = _month_bounds()
            row = db.execute(
                "SELECT COUNT(*) as cnt FROM retrieval_calls "
                "WHERE adapter_type = ? AND called_at >= ? AND called_at <= ?",
                (adapter_type, month_start, month_end),
            ).fetchone()
            if row and row["cnt"] >= monthly_cap:
                logger.warning(
                    "budget_cap_exceeded: %s monthly cap %d reached (%d calls this month)",
                    adapter_type, monthly_cap, row["cnt"],
                )
                return False

        return True
    finally:
        db.close()


def record_call(adapter_type: str, query: str, status: str, error: str | None = None) -> None:
    """Record a retrieval call in the tracking table."""
    db = get_connection()
    try:
        db.execute(
            "INSERT INTO retrieval_calls (adapter_type, query, status, error_message, called_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (adapter_type, query, status, error, datetime.now(UTC).isoformat()),
        )
        db.commit()
    except Exception:
        logger.debug("record_call_failed", exc_info=True)
    finally:
        db.close()


def get_usage(adapter_type: str = "tavily") -> dict:
    """Return current usage counts for the budget status endpoint."""
    db = get_connection()
    try:
        day_start, day_end = _today_bounds()
        month_start, month_end = _month_bounds()

        daily_count = db.execute(
            "SELECT COUNT(*) as cnt FROM retrieval_calls "
            "WHERE adapter_type = ? AND called_at >= ? AND called_at <= ?",
            (adapter_type, day_start, day_end),
        ).fetchone()["cnt"]

        monthly_count = db.execute(
            "SELECT COUNT(*) as cnt FROM retrieval_calls "
            "WHERE adapter_type = ? AND called_at >= ? AND called_at <= ?",
            (adapter_type, month_start, month_end),
        ).fetchone()["cnt"]

        daily_errors = db.execute(
            "SELECT COUNT(*) as cnt FROM retrieval_calls "
            "WHERE adapter_type = ? AND status = 'failed' AND called_at >= ? AND called_at <= ?",
            (adapter_type, day_start, day_end),
        ).fetchone()["cnt"]

        return {
            "adapter_type": adapter_type,
            "daily_count": daily_count,
            "monthly_count": monthly_count,
            "daily_errors": daily_errors,
        }
    finally:
        db.close()
