"""Pipeline API routes."""

from __future__ import annotations

import json
import queue
import queue as queue_module
import threading
from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from seeker_os.api.schemas import (
    PipelineRunRequest, PipelineRunSummary, PipelineRunRecord,
)
from seeker_os.database import get_connection

router = APIRouter(prefix="/api/pipeline", tags=["pipeline"])


@router.post("/run", response_model=PipelineRunSummary)
def run_pipeline(body: PipelineRunRequest):
    """Trigger a full pipeline run (or specific tiers/queries)."""
    from seeker_os.config import Settings
    from seeker_os.pipeline.runner import run_pipeline as _run

    settings = Settings()
    result = _run(
        settings,
        queries=body.queries,
        tiers=body.tiers,
        dry_run=body.dry_run,
    )
    return result.model_dump()


@router.post("/run/stream")
def run_pipeline_stream(body: PipelineRunRequest):
    """Trigger a pipeline run with SSE progress streaming.

    Returns a text/event-stream with PipelineProgressEvent objects as they occur,
    followed by a final 'done' event with the PipelineRunSummary.
    """
    from seeker_os.config import Settings
    from seeker_os.pipeline.runner import run_pipeline as _run

    settings = Settings()
    event_queue: queue.Queue = queue.Queue()

    def progress_cb(event):
        event_queue.put(event)

    def run_in_thread():
        try:
            result = _run(
                settings,
                queries=body.queries,
                tiers=body.tiers,
                dry_run=body.dry_run,
                progress_cb=progress_cb,
            )
            event_queue.put(("done", result))
        except Exception as e:
            event_queue.put(("error", str(e)))

    thread = threading.Thread(target=run_in_thread, daemon=True)
    thread.start()

    def event_stream():
        while True:
            try:
                item = event_queue.get(timeout=300)
            except queue_module.Empty:
                yield 'data: {"type":"error","message":"Pipeline timeout"}\n\n'
                break
            if isinstance(item, tuple):
                if item[0] == "done":
                    yield f"event: done\ndata: {json.dumps(item[1].model_dump())}\n\n"
                    break
                elif item[0] == "error":
                    yield f"event: error\ndata: {json.dumps({'error': item[1]})}\n\n"
                    break
            else:
                yield f"data: {item.model_dump_json()}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.post("/run/tier/{tier}", response_model=PipelineRunSummary)
def run_tier(tier: int):
    """Run a specific tier only."""
    from seeker_os.config import Settings
    from seeker_os.pipeline.runner import run_pipeline as _run

    if tier < 1 or tier > 5:
        raise HTTPException(status_code=400, detail="Tier must be 1-5")

    settings = Settings()
    result = _run(settings, tiers=[tier])
    return result.model_dump()


@router.get("/runs", response_model=list[PipelineRunRecord])
def list_runs(limit: int = 20):
    """List pipeline run history."""
    db = get_connection()
    rows = db.execute(
        "SELECT * FROM pipeline_runs ORDER BY started_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    db.close()
    return [
        PipelineRunRecord(
            id=r["id"],
            run_id=r["run_id"] or "",
            started_at=r["started_at"] or "",
            completed_at=r["completed_at"],
            cards_fetched=r["cards_fetched"] or 0,
            cards_new=r["cards_new"] or 0,
            cards_survived_tier2=r["cards_survived_tier2"] or 0,
            jds_fetched=r["jds_fetched"] or 0,
            jobs_scored=r["jobs_scored"] or 0,
            jobs_ready=r["jobs_ready"] or 0,
            status=r["status"] or "",
        )
        for r in rows
    ]


@router.get("/runs/{run_id}", response_model=PipelineRunRecord)
def get_run(run_id: str):
    """Get details of a specific pipeline run."""
    db = get_connection()
    row = db.execute(
        "SELECT * FROM pipeline_runs WHERE run_id = ?", (run_id,)
    ).fetchone()
    db.close()
    if not row:
        raise HTTPException(status_code=404, detail=f"Run {run_id} not found")
    return PipelineRunRecord(
        id=row["id"],
        run_id=row["run_id"] or "",
        started_at=row["started_at"] or "",
        completed_at=row["completed_at"],
        cards_fetched=row["cards_fetched"] or 0,
        cards_new=row["cards_new"] or 0,
        cards_survived_tier2=row["cards_survived_tier2"] or 0,
        jds_fetched=row["jds_fetched"] or 0,
        jobs_scored=row["jobs_scored"] or 0,
        jobs_ready=row["jobs_ready"] or 0,
        status=row["status"] or "",
    )
