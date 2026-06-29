"""Queries API routes."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from seeker_os.api.schemas import QuerySummary, QueryCreate, QueryUpdate, MessageResponse
from seeker_os.database import get_connection

router = APIRouter(prefix="/api/queries", tags=["queries"])


@router.get("", response_model=list[QuerySummary])
def list_queries():
    """List all search queries from DB."""
    db = get_connection()
    try:
        rows = db.execute(
            "SELECT * FROM search_queries ORDER BY label ASC"
        ).fetchall()
        return [
            QuerySummary(
                id=r["id"],
                source_id=r["source_id"] or "hiring_cafe",
                slug=r["query_slug"] or "",
                label=r["label"] or "",
                commitment=r["commitment_filter"] or "full_time",
                max_pages=r["max_pages"] or 1,
                enabled=bool(r["enabled"]),
                last_run_at=r["last_run_at"],
                search_query=r["search_query"] if "search_query" in r.keys() else None,
            )
            for r in rows
        ]
    finally:
        db.close()


@router.post("", response_model=MessageResponse)
def create_query(body: QueryCreate):
    """Create a new search query."""
    db = get_connection()
    try:
        now = datetime.now(timezone.utc).isoformat()
        db.execute(
            """
            INSERT INTO search_queries
            (source_id, query_slug, label, commitment_filter, max_pages, enabled, notes, search_query)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (body.source_id, body.slug, body.label, body.commitment, body.max_pages, body.enabled, now, body.search_query),
        )
        db.commit()
        return MessageResponse(message=f"Query '{body.slug}' created")
    finally:
        db.close()


@router.patch("/{query_id}", response_model=MessageResponse)
def update_query(query_id: int, body: QueryUpdate):
    """Update a search query."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM search_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

        if body.label is not None:
            db.execute("UPDATE search_queries SET label=? WHERE id=?", (body.label, query_id))
        if body.commitment is not None:
            db.execute("UPDATE search_queries SET commitment_filter=? WHERE id=?", (body.commitment, query_id))
        if body.max_pages is not None:
            db.execute("UPDATE search_queries SET max_pages=? WHERE id=?", (body.max_pages, query_id))
        if body.enabled is not None:
            db.execute("UPDATE search_queries SET enabled=? WHERE id=?", (body.enabled, query_id))
        if body.search_query is not None:
            db.execute("UPDATE search_queries SET search_query=? WHERE id=?", (body.search_query, query_id))
        db.commit()
        return MessageResponse(message=f"Query {query_id} updated")
    finally:
        db.close()


@router.delete("/{query_id}", response_model=MessageResponse)
def delete_query(query_id: int):
    """Delete a search query."""
    db = get_connection()
    try:
        row = db.execute("SELECT * FROM search_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

        db.execute("DELETE FROM search_queries WHERE id=?", (query_id,))
        db.commit()
        return MessageResponse(message=f"Query {query_id} deleted")
    finally:
        db.close()


@router.post("/{query_id}/run", response_model=dict)
def run_single_query(query_id: int, force_full_pull: bool = False):
    """Run a single query (Tier 1 only).

    When force_full_pull is False and the query has a search_query, the adapter
    requests only jobs posted since last_run_at (incremental search).
    When force_full_pull is True, no date filter is applied (full pull).
    """
    from seeker_os.config import Settings
    from seeker_os.pipeline.runner import run_pipeline as _run

    db = get_connection()
    try:
        row = db.execute("SELECT * FROM search_queries WHERE id = ?", (query_id,)).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail=f"Query {query_id} not found")

        settings = Settings()
        result = _run(
            settings,
            queries=[row["query_slug"]],
            tiers=[1],
            force_full_pull=force_full_pull,
        )
        return result.model_dump()
    finally:
        db.close()
