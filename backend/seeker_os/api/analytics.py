"""Analytics API routes."""

from __future__ import annotations

import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, HTTPException, Query

from seeker_os.api.schemas import (
    AgingBucket,
    AgingReport,
    CalibrationReport,
    FunnelStats,
    LangfuseStatusResponse,
    MovementEvent,
    MovementReport,
    ObservabilityCall,
    ObservabilityEvaluation,
    ObservabilityOperation,
    ObservabilityOperationDetail,
    ObservabilitySummary,
    ObservabilityTaskSummary,
    PricingRouteComparison,
    ResponseRateStats,
    SignalQualityReport,
    SpendByModel,
    SpendByTask,
    SpendReport,
    SLOMetric,
    SLOStatusResponse,
    BudgetStatusResponse,
    VerdictDistribution,
)
from seeker_os.config import get_settings
from seeker_os.database import get_connection
from seeker_os.scoring.calibration import build_calibration_report

router = APIRouter(prefix="/api/analytics", tags=["analytics"])
logger = logging.getLogger(__name__)


def _resolve_artifact_jobs(db, operations: list[ObservabilityOperation]) -> None:
    """Populate job_id, job_title, company on operations with artifacts."""
    # Resume artifacts: resumes.artifact_id → resumes.job_id → jobs
    resume_ids = [
        op.artifact_id for op in operations
        if op.artifact_type == "resume" and op.artifact_id is not None
    ]
    if resume_ids:
        placeholders = ",".join("?" * len(resume_ids))
        rows = db.execute(
            f"""SELECT r.id AS resume_id, r.job_id, j.title, j.company
                FROM resumes r JOIN jobs j ON j.id = r.job_id
                WHERE r.id IN ({placeholders})""",
            resume_ids,
        ).fetchall()
        for row in rows:
            for op in operations:
                if op.artifact_type == "resume" and op.artifact_id == row["resume_id"]:
                    op.job_id = row["job_id"]
                    op.job_title = row["title"] or ""
                    op.company = row["company"] or ""

    # Job analysis artifacts: job_analyses.id → job_analyses.job_id → jobs
    analysis_ids = [
        op.artifact_id for op in operations
        if op.artifact_type == "job_analysis" and op.artifact_id is not None
    ]
    if analysis_ids:
        placeholders = ",".join("?" * len(analysis_ids))
        rows = db.execute(
            f"""SELECT ja.id AS analysis_id, ja.job_id, j.title, j.company
                FROM job_analyses ja JOIN jobs j ON j.id = ja.job_id
                WHERE ja.id IN ({placeholders})""",
            analysis_ids,
        ).fetchall()
        for row in rows:
            for op in operations:
                if op.artifact_type == "job_analysis" and op.artifact_id == row["analysis_id"]:
                    op.job_id = row["job_id"]
                    op.job_title = row["title"] or ""
                    op.company = row["company"] or ""

    # Company research artifacts: company_research.id → triggered_by_job_id → jobs
    research_ids = [
        op.artifact_id for op in operations
        if op.artifact_type == "company_research" and op.artifact_id is not None
    ]
    if research_ids:
        placeholders = ",".join("?" * len(research_ids))
        rows = db.execute(
            f"""SELECT cr.id AS research_id, cr.triggered_by_job_id, j.title, j.company
                FROM company_research cr JOIN jobs j ON j.id = cr.triggered_by_job_id
                WHERE cr.id IN ({placeholders})""",
            research_ids,
        ).fetchall()
        for row in rows:
            for op in operations:
                if op.artifact_type == "company_research" and op.artifact_id == row["research_id"]:
                    op.job_id = row["triggered_by_job_id"]
                    op.job_title = row["title"] or ""
                    op.company = row["company"] or ""

    # Job artifacts: artifact_id IS the job_id
    job_ids = [
        op.artifact_id for op in operations
        if op.artifact_type == "job" and op.artifact_id is not None
    ]
    if job_ids:
        placeholders = ",".join("?" * len(job_ids))
        rows = db.execute(
            f"""SELECT id, title, company FROM jobs WHERE id IN ({placeholders})""",
            job_ids,
        ).fetchall()
        for row in rows:
            for op in operations:
                if op.artifact_type == "job" and op.artifact_id == row["id"]:
                    op.job_id = row["id"]
                    op.job_title = row["title"] or ""
                    op.company = row["company"] or ""


@router.get("/llm-observability", response_model=ObservabilitySummary)
def get_llm_observability():
    """Privacy-safe LLM reliability, cost, and quality summary."""
    db = get_connection()
    try:
        calls = db.execute(
            """SELECT COUNT(*) AS total,
                      COALESCE(SUM(estimated_cost), 0) AS cost,
                      SUM(CASE WHEN status IN ('failed', 'empty') THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN error_type = 'truncated' THEN 1 ELSE 0 END) AS truncated
               FROM llm_calls"""
        ).fetchone()
        validations = db.execute(
            """SELECT COUNT(*) AS total,
                      SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed
               FROM llm_evaluations WHERE metric_name = 'accuracy_validation'"""
        ).fetchone()
        claim_counts = db.execute(
            """SELECT
                 SUM(CASE WHEN label = 'unsupported' THEN 1 ELSE 0 END) AS unsupported,
                 SUM(CASE WHEN label = 'overstated' THEN 1 ELSE 0 END) AS overstated
               FROM llm_evaluations WHERE metric_name = 'claim_traceability'"""
        ).fetchone()
        passing = validations["passed"] or 0
        operation_cost = db.execute(
            """SELECT COALESCE(SUM(c.estimated_cost), 0) AS cost
               FROM llm_calls c
               WHERE c.operation_id IN (
                   SELECT operation_id FROM llm_evaluations
                   WHERE metric_name = 'accuracy_validation' AND passed = 1
               )"""
        ).fetchone()["cost"]
        operation_rows = db.execute(
            """SELECT operation_id, MIN(started_at) AS started_at,
                      MAX(completed_at) AS completed_at, COUNT(*) AS calls,
                      SUM(estimated_cost) AS cost,
                      CASE WHEN SUM(CASE WHEN status IN ('failed', 'empty') THEN 1 ELSE 0 END) > 0
                           THEN 'failed' ELSE 'succeeded' END AS status,
                      MAX(artifact_id) AS artifact_id,
                      MAX(artifact_type) AS artifact_type
               FROM llm_calls WHERE operation_id IS NOT NULL
               GROUP BY operation_id ORDER BY started_at DESC LIMIT 20"""
        ).fetchall()
        recent = []
        for row in operation_rows:
            validation = db.execute(
                """SELECT passed FROM llm_evaluations
                   WHERE operation_id = ? AND metric_name = 'accuracy_validation'
                   ORDER BY evaluated_at DESC LIMIT 1""",
                (row["operation_id"],),
            ).fetchone()
            recent.append(ObservabilityOperation(
                operation_id=row["operation_id"], started_at=row["started_at"],
                completed_at=row["completed_at"], status=row["status"], calls=row["calls"],
                estimated_cost=round(row["cost"] or 0, 6),
                validation_passed=bool(validation["passed"]) if validation else None,
                artifact_type=row["artifact_type"],
                artifact_id=row["artifact_id"],
            ))
        validation_rate = round(passing / validations["total"] * 100, 1) if validations["total"] else None
        task_rows = db.execute(
            "SELECT DISTINCT task FROM llm_calls WHERE task IS NOT NULL ORDER BY task"
        ).fetchall()
        raw_tasks = [r["task"] for r in task_rows]
        available_tasks: list[str] = []
        seen_resume = False
        for t in raw_tasks:
            if t.startswith("resume_generation"):
                if not seen_resume:
                    available_tasks.append("resume_generation")
                    seen_resume = True
            else:
                available_tasks.append(t)
        _resolve_artifact_jobs(db, recent)
        return ObservabilitySummary(
            total_calls=calls["total"], total_estimated_cost=round(calls["cost"], 6),
            failed_calls=calls["failed"] or 0, truncated_calls=calls["truncated"] or 0,
            validation_pass_rate=validation_rate,
            unsupported_claims=claim_counts["unsupported"] or 0,
            overstated_claims=claim_counts["overstated"] or 0,
            cost_per_passing_resume=round(operation_cost / passing, 6) if passing else None,
            available_tasks=available_tasks,
            recent_operations=recent,
        )
    finally:
        db.close()


@router.get("/llm-observability/task-operations", response_model=list[ObservabilityOperation])
def get_task_operations(
    task: str = Query(..., description="Task name to filter by. Use 'resume_generation' to match both standard and high_value variants."),
    model: str | None = Query(None, description="Filter by specific model."),
):
    """Return recent operations for a specific LLM task.

    For tasks with operation_id (e.g. resume generation), groups calls by
    operation_id. For tasks without operation_id, returns individual calls.
    """
    db = get_connection()
    try:
        if task == "resume_generation":
            task_filter = "task LIKE 'resume_generation%'"
            params: tuple = ()
        else:
            task_filter = "task = ?"
            params = (task,)

        model_filter = ""
        if model:
            model_filter = " AND actual_model = ?"
            params = params + (model,)

        # Grouped operations (have operation_id)
        grouped_rows = db.execute(
            f"""SELECT operation_id, MIN(started_at) AS started_at,
                      MAX(completed_at) AS completed_at, COUNT(*) AS calls,
                      SUM(estimated_cost) AS cost,
                      CASE WHEN SUM(CASE WHEN status IN ('failed', 'empty') THEN 1 ELSE 0 END) > 0
                           THEN 'failed' ELSE 'succeeded' END AS status,
                      MAX(artifact_id) AS artifact_id,
                      MAX(artifact_type) AS artifact_type,
                      MAX(actual_model) AS model,
                      SUM(input_tokens + output_tokens) AS total_tokens,
                      CAST(SUM(latency_ms) AS INTEGER) AS latency_ms,
                      MIN(task) AS task
               FROM llm_calls WHERE operation_id IS NOT NULL AND {task_filter}{model_filter}
               GROUP BY operation_id ORDER BY started_at DESC LIMIT 20""",
            params,
        ).fetchall()

        operations: list[ObservabilityOperation] = []
        for row in grouped_rows:
            validation = db.execute(
                """SELECT passed FROM llm_evaluations
                   WHERE operation_id = ? AND metric_name = 'accuracy_validation'
                   ORDER BY evaluated_at DESC LIMIT 1""",
                (row["operation_id"],),
            ).fetchone()
            operations.append(ObservabilityOperation(
                operation_id=row["operation_id"], started_at=row["started_at"],
                completed_at=row["completed_at"], status=row["status"], calls=row["calls"],
                estimated_cost=round(row["cost"] or 0, 6),
                validation_passed=bool(validation["passed"]) if validation else None,
                artifact_type=row["artifact_type"],
                artifact_id=row["artifact_id"],
                task=row["task"],
                grouped=True,
                model=row["model"],
                total_tokens=row["total_tokens"] or 0,
                latency_ms=row["latency_ms"] or 0,
            ))

        # Ungrouped calls (no operation_id)
        ungrouped_rows = db.execute(
            f"""SELECT call_id, started_at, completed_at, status,
                      estimated_cost, artifact_id, artifact_type, task,
                      actual_model AS model,
                      input_tokens + output_tokens AS total_tokens,
                      latency_ms
               FROM llm_calls WHERE operation_id IS NULL AND {task_filter}{model_filter}
               ORDER BY started_at DESC LIMIT 20""",
            params,
        ).fetchall()

        for row in ungrouped_rows:
            operations.append(ObservabilityOperation(
                operation_id=row["call_id"], started_at=row["started_at"],
                completed_at=row["completed_at"], status=row["status"], calls=1,
                estimated_cost=round(row["estimated_cost"] or 0, 6),
                validation_passed=None,
                artifact_type=row["artifact_type"],
                artifact_id=row["artifact_id"],
                task=row["task"],
                grouped=False,
                model=row["model"],
                total_tokens=row["total_tokens"] or 0,
                latency_ms=row["latency_ms"] or 0,
            ))

        operations.sort(key=lambda op: op.started_at, reverse=True)
        _resolve_artifact_jobs(db, operations)
        return operations[:20]
    finally:
        db.close()


@router.get("/llm-observability/task-summary", response_model=ObservabilityTaskSummary)
def get_task_summary(
    task: str = Query(..., description="Task name to summarize."),
    model: str | None = Query(None, description="Filter by specific model."),
):
    """Return aggregate stats for a specific LLM task."""
    db = get_connection()
    try:
        if task == "resume_generation":
            task_filter = "task LIKE 'resume_generation%'"
            params: tuple = ()
        else:
            task_filter = "task = ?"
            params = (task,)

        model_filter = ""
        if model:
            model_filter = " AND actual_model = ?"
            params = params + (model,)

        row = db.execute(
            f"""SELECT COUNT(*) AS calls,
                      COALESCE(SUM(estimated_cost), 0) AS cost,
                      SUM(CASE WHEN status IN ('failed', 'empty') THEN 1 ELSE 0 END) AS failed,
                      SUM(CASE WHEN error_type = 'truncated' THEN 1 ELSE 0 END) AS truncated,
                      CAST(AVG(latency_ms) AS INTEGER) AS avg_latency,
                      SUM(input_tokens + output_tokens) AS total_tokens
               FROM llm_calls WHERE {task_filter}{model_filter}""",
            params,
        ).fetchone()

        models = db.execute(
            f"""SELECT DISTINCT actual_model FROM llm_calls
               WHERE {task_filter} AND actual_model IS NOT NULL
               ORDER BY actual_model""",
            params[:1] if task != "resume_generation" else (),
        ).fetchall()
        models_used = [r["actual_model"] for r in models]

        # Resume-specific metrics
        validation_pass_rate: float | None = None
        unsupported_claims = 0
        overstated_claims = 0
        cost_per_passing_resume: float | None = None

        if task == "resume_generation":
            validations = db.execute(
                """SELECT COUNT(*) AS total,
                          SUM(CASE WHEN passed = 1 THEN 1 ELSE 0 END) AS passed
                   FROM llm_evaluations WHERE metric_name = 'accuracy_validation'"""
            ).fetchone()
            total_val = validations["total"] or 0
            passing = validations["passed"] or 0
            validation_pass_rate = round(passing / total_val * 100, 1) if total_val else None

            claim_counts = db.execute(
                """SELECT
                     SUM(CASE WHEN label = 'unsupported' THEN 1 ELSE 0 END) AS unsupported,
                     SUM(CASE WHEN label = 'overstated' THEN 1 ELSE 0 END) AS overstated
                   FROM llm_evaluations WHERE metric_name = 'claim_traceability'"""
            ).fetchone()
            unsupported_claims = claim_counts["unsupported"] or 0
            overstated_claims = claim_counts["overstated"] or 0

            if passing:
                op_cost = db.execute(
                    """SELECT COALESCE(SUM(c.estimated_cost), 0) AS cost
                       FROM llm_calls c
                       WHERE c.operation_id IN (
                           SELECT operation_id FROM llm_evaluations
                           WHERE metric_name = 'accuracy_validation' AND passed = 1
                       )"""
                ).fetchone()["cost"]
                cost_per_passing_resume = round(op_cost / passing, 6)

        return ObservabilityTaskSummary(
            task=task,
            calls=row["calls"] or 0,
            estimated_cost=round(row["cost"] or 0, 6),
            failed_calls=row["failed"] or 0,
            truncated_calls=row["truncated"] or 0,
            avg_latency_ms=row["avg_latency"] or 0,
            total_tokens=row["total_tokens"] or 0,
            models_used=models_used,
            validation_pass_rate=validation_pass_rate,
            unsupported_claims=unsupported_claims,
            overstated_claims=overstated_claims,
            cost_per_passing_resume=cost_per_passing_resume,
        )
    finally:
        db.close()


@router.get("/llm-observability/operations/{operation_id}", response_model=ObservabilityOperationDetail)
def get_llm_operation(operation_id: str):
    """Return safe lineage for one correlated LLM workflow."""
    db = get_connection()
    try:
        call_rows = db.execute(
            "SELECT * FROM llm_calls WHERE operation_id = ? ORDER BY started_at", (operation_id,)
        ).fetchall()
        if not call_rows:
            raise HTTPException(status_code=404, detail="LLM operation not found")
        evaluation_rows = db.execute(
            "SELECT * FROM llm_evaluations WHERE operation_id = ? ORDER BY evaluated_at",
            (operation_id,),
        ).fetchall()
        artifact_type = next((r["artifact_type"] for r in call_rows if r["artifact_type"]), None)
        artifact_id = next((r["artifact_id"] for r in call_rows if r["artifact_id"]), None)
        job_id: int | None = None
        job_title: str | None = None
        company: str | None = None
        if artifact_type and artifact_id is not None:
            if artifact_type == "resume":
                job_row = db.execute(
                    """SELECT j.id, j.title, j.company
                       FROM resumes r JOIN jobs j ON j.id = r.job_id
                       WHERE r.id = ?""",
                    (artifact_id,),
                ).fetchone()
            elif artifact_type == "job_analysis":
                job_row = db.execute(
                    """SELECT j.id, j.title, j.company
                       FROM job_analyses ja JOIN jobs j ON j.id = ja.job_id
                       WHERE ja.id = ?""",
                    (artifact_id,),
                ).fetchone()
            elif artifact_type == "company_research":
                job_row = db.execute(
                    """SELECT j.id, j.title, j.company
                       FROM company_research cr JOIN jobs j ON j.id = cr.triggered_by_job_id
                       WHERE cr.id = ?""",
                    (artifact_id,),
                ).fetchone()
            elif artifact_type == "job":
                job_row = db.execute(
                    "SELECT id, title, company FROM jobs WHERE id = ?",
                    (artifact_id,),
                ).fetchone()
            else:
                job_row = None
            if job_row:
                job_id = job_row["id"]
                job_title = job_row["title"] or None
                company = job_row["company"] or None
        return ObservabilityOperationDetail(
            operation_id=operation_id,
            artifact_type=artifact_type,
            artifact_id=artifact_id,
            job_id=job_id,
            job_title=job_title,
            company=company,
            calls=[ObservabilityCall(
                call_id=r["call_id"], parent_call_id=r["parent_call_id"], task=r["task"],
                provider=r["actual_provider"] or r["requested_provider"],
                model=r["actual_model"] or r["requested_model"], status=r["status"],
                error_type=r["error_type"], stop_reason=r["stop_reason"],
                temperature=r["temperature"], max_tokens=r["max_tokens"],
                prompt_name=r["prompt_name"], prompt_version=r["prompt_version"],
                route_reason=r["route_reason"],
                input_tokens=r["input_tokens"],
                output_tokens=r["output_tokens"], latency_ms=r["latency_ms"],
                estimated_cost=r["estimated_cost"], started_at=r["started_at"],
            ) for r in call_rows],
            evaluations=[ObservabilityEvaluation(
                evaluation_id=r["evaluation_id"], evaluator_name=r["evaluator_name"],
                evaluator_type=r["evaluator_type"] or "",
                evaluator_version=r["evaluator_version"] or "",
                metric_name=r["metric_name"], score=r["score"],
                label=r["label"],
                passed=bool(r["passed"]) if r["passed"] is not None else None,
                evaluated_at=r["evaluated_at"],
            ) for r in evaluation_rows],
        )
    finally:
        db.close()


@router.get("/langfuse-status", response_model=LangfuseStatusResponse)
def get_langfuse_status():
    """Langfuse tracing sink status for UI display and connection debugging."""
    from seeker_os.observability.langfuse_sink import get_status

    return LangfuseStatusResponse(**get_status())


@router.get("/slo-status", response_model=SLOStatusResponse)
def get_slo_status():
    """SLO status — compare actuals vs targets from observability.yml.

    Metrics:
    - analysis_latency_p95_ms: p95 latency for jd_analysis calls in the SLO window
    - pipeline_availability: fraction of distinct operation_ids with no failed calls
    - daily_spend: total estimated_cost for today vs daily_spend_budget_usd
    """
    from datetime import UTC, datetime, timedelta

    settings = get_settings()
    slo = settings.observability.slo
    window_start = (datetime.now(UTC) - timedelta(hours=slo.slo_window_hours)).isoformat()

    db = get_connection()
    try:
        # 1. Analysis latency p95
        latency_rows = db.execute(
            """SELECT latency_ms FROM llm_calls
               WHERE task = 'jd_analysis'
                 AND status = 'succeeded'
                 AND started_at >= ?
               ORDER BY latency_ms""",
            (window_start,),
        ).fetchall()
        if latency_rows:
            latencies = [r["latency_ms"] for r in latency_rows]
            p95_idx = int(len(latencies) * 0.95)
            p95_actual = latencies[min(p95_idx, len(latencies) - 1)]
        else:
            p95_actual = 0

        # 2. Pipeline availability
        total_ops = db.execute(
            "SELECT COUNT(DISTINCT operation_id) as cnt FROM llm_calls WHERE started_at >= ? AND operation_id IS NOT NULL",
            (window_start,),
        ).fetchone()["cnt"]
        failed_ops = db.execute(
            """SELECT COUNT(DISTINCT operation_id) as cnt FROM llm_calls
               WHERE started_at >= ? AND operation_id IS NOT NULL AND status = 'failed'""",
            (window_start,),
        ).fetchone()["cnt"]
        availability_actual = ((total_ops - failed_ops) / total_ops) if total_ops > 0 else 1.0

        # 3. Daily spend
        day_start = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
        spend_row = db.execute(
            "SELECT COALESCE(SUM(estimated_cost), 0) as total FROM llm_calls WHERE started_at >= ?",
            (day_start,),
        ).fetchone()
        daily_spend = spend_row["total"] if spend_row else 0.0
    finally:
        db.close()

    metrics = [
        SLOMetric(
            name="analysis_latency_p95_ms",
            target=float(slo.analysis_latency_p95_ms),
            actual=float(p95_actual),
            unit="ms",
            passing=p95_actual <= slo.analysis_latency_p95_ms,
        ),
        SLOMetric(
            name="pipeline_availability",
            target=slo.pipeline_availability_target,
            actual=availability_actual,
            unit="%",
            passing=availability_actual >= slo.pipeline_availability_target,
        ),
    ]

    return SLOStatusResponse(
        window_hours=slo.slo_window_hours,
        metrics=metrics,
        daily_spend_usd=daily_spend,
        daily_spend_budget_usd=slo.daily_spend_budget_usd,
    )


@router.get("/budget-status", response_model=BudgetStatusResponse)
def get_budget_status():
    """Budget usage for paid retrieval calls (Tavily)."""
    from seeker_os.observability.budget_guard import get_usage

    settings = get_settings()
    caps = settings.observability.budget_caps

    usage = get_usage("tavily")
    daily_cap = caps.tavily_daily_cap
    monthly_cap = caps.tavily_monthly_cap

    return BudgetStatusResponse(
        adapter_type="tavily",
        daily_count=usage["daily_count"],
        daily_cap=daily_cap,
        monthly_count=usage["monthly_count"],
        monthly_cap=monthly_cap,
        daily_errors=usage["daily_errors"],
        daily_remaining=(daily_cap - usage["daily_count"]) if daily_cap > 0 else None,
        monthly_remaining=(monthly_cap - usage["monthly_count"]) if monthly_cap > 0 else None,
    )


@router.get("/funnel", response_model=FunnelStats)
def get_funnel_stats():
    """Pipeline funnel stats — cumulative counts at each tier and by status.

    The funnel is: All Jobs → Tier 1 (Discovery) → Tier 2 (Filtering) → Scored.
    JD fetch is enrichment, not a funnel gate — shown as a separate metric.
    """
    db = get_connection()
    try:
        # Total
        total = db.execute("SELECT COUNT(*) as c FROM jobs").fetchone()["c"]

        # By status
        status_rows = db.execute(
            "SELECT status, COUNT(*) as c FROM jobs GROUP BY status"
        ).fetchall()
        by_status = {r["status"]: r["c"] for r in status_rows}

        # By tier (raw counts — jobs whose highest passed tier is N)
        tier_rows = db.execute(
            "SELECT tier_passed, COUNT(*) as c FROM jobs GROUP BY tier_passed"
        ).fetchall()
        by_tier = {r["tier_passed"]: r["c"] for r in tier_rows}

        # Cumulative funnel: jobs that reached AT LEAST each stage
        # Every job in the DB has tier_passed >= 1 (that's how it got inserted),
        # so "All Jobs" and "Discovery" are the same — we collapse them.
        # tier_passed >= 2 means passed hard filters
        # tier_passed >= 4 means scored (tier 3 = JD fetch is enrichment, not a gate)
        passed_t2 = db.execute("SELECT COUNT(*) as c FROM jobs WHERE tier_passed >= 2").fetchone()["c"]
        scored = db.execute("SELECT COUNT(*) as c FROM jobs WHERE tier_passed >= 4").fetchone()["c"]

        funnel = [
            {"tier": 1, "label": "Discovered", "count": total},
            {"tier": 2, "label": "Passed Filters", "count": passed_t2},
            {"tier": 4, "label": "Passed Scoring", "count": scored},
        ]

        # JD fetch stats — for jobs that passed tier 2 (the ones that need JD fetch)
        jd_fetch_rows = db.execute(
            """
            SELECT jd_fetch_status, COUNT(*) as c
            FROM jobs WHERE tier_passed >= 2
            GROUP BY jd_fetch_status
            """
        ).fetchall()
        jd_stats = {r["jd_fetch_status"]: r["c"] for r in jd_fetch_rows}
        jd_fetch_total = sum(jd_stats.values())
        jd_fetch_success = jd_stats.get("fetched", 0)
        jd_fetch_failed = jd_stats.get("failed", 0)
        jd_fetch_pending = jd_stats.get("pending", 0)

        # By ATS source
        ats_rows = db.execute(
            "SELECT ats_source, COUNT(*) as c FROM jobs WHERE ats_source IS NOT NULL GROUP BY ats_source ORDER BY c DESC"
        ).fetchall()
        by_ats = {r["ats_source"] or "unknown": r["c"] for r in ats_rows}

        # Rejection reasons
        reason_rows = db.execute(
            "SELECT reject_reason, COUNT(*) as c FROM jobs WHERE reject_reason IS NOT NULL AND reject_reason != '' GROUP BY reject_reason ORDER BY c DESC LIMIT 20"
        ).fetchall()
        rejection_reasons = {r["reject_reason"]: r["c"] for r in reason_rows}

        # Score distribution
        score_rows = db.execute(
            """
            SELECT
              CASE
                WHEN score IS NULL THEN 'unscored'
                WHEN score >= 8 THEN '8-10'
                WHEN score >= 6 THEN '6-8'
                WHEN score >= 4 THEN '4-6'
                WHEN score >= 2 THEN '2-4'
                ELSE '0-2'
              END as bucket,
              COUNT(*) as c
            FROM jobs GROUP BY bucket
            """
        ).fetchall()
        score_dist = {r["bucket"]: r["c"] for r in score_rows}

        return FunnelStats(
            total_jobs=total,
            discovered=by_status.get("discovered", 0),
            filtered=by_status.get("filtered", 0),
            jd_fetched=by_status.get("jd_fetched", 0),
            ready=by_status.get("ready", 0),
            rejected=by_status.get("rejected", 0),
            duplicate_flagged=by_status.get("duplicate_flagged", 0),
            capped=by_status.get("capped", 0),
            funnel=funnel,
            jd_fetch_total=jd_fetch_total,
            jd_fetch_success=jd_fetch_success,
            jd_fetch_failed=jd_fetch_failed,
            jd_fetch_pending=jd_fetch_pending,
            by_tier=by_tier,
            by_status=by_status,
            by_ats_source=by_ats,
            rejection_reasons=rejection_reasons,
            score_distribution=score_dist,
        )
    finally:
        db.close()


@router.get("/calibration", response_model=CalibrationReport)
def get_calibration_report(
    bucket_width: float | None = Query(
        default=None,
        gt=0,
        description="Override the configured net-score bucket width for this request",
    ),
):
    """Scoring calibration report — rubric scores vs. actual apply/skip decisions.

    Joins jobs (score, research_adjusted_score, net_score, analysis_verdict)
    against the application_events log. Produces the score-bucket vs.
    decision-rate table, false-positive/false-negative miss lists, and
    per-modifier empirical precision. Bucket width and miss thresholds come
    from scoring_rubric.yml (calibration section).
    """
    scoring = get_settings().scoring
    if scoring is None:
        raise HTTPException(
            status_code=409,
            detail="No scoring rubric configured — scoring_rubric.yml is required for calibration",
        )

    db = get_connection()
    try:
        return build_calibration_report(db, scoring, bucket_width=bucket_width)
    finally:
        db.close()


@router.get("/response-rate", response_model=ResponseRateStats)
def get_response_rate():
    """Response rate stats (placeholder — application tracking is Phase 2+)."""
    return ResponseRateStats(
        total_applied=0,
        total_responded=0,
        response_rate=0.0,
        by_source={},
    )


# ---------------------------------------------------------------------------
# Phase 2 — Dashboard analytics endpoints
# ---------------------------------------------------------------------------


@router.get("/movement", response_model=MovementReport)
def get_movement(
    days: int = Query(7, ge=1, le=90, description="Lookback window in days"),
    limit: int = Query(50, ge=1, le=200, description="Max events to return"),
):
    """Recent status-transition events (movement feed).

    Returns the most recent application_events that represent meaningful
    status changes — applied, engaged, offers, etc.

    Rejected and skipped events are excluded from the row list and instead
    returned as grouped counts (rejection_count + rejection_breakdown).
    Display-level only — events are never mutated and remain queryable elsewhere.
    """
    db = get_connection()
    try:
        cutoff = (datetime.now(UTC) - timedelta(days=days)).isoformat()
        rows = db.execute(
            """
            SELECT ae.job_id, ae.event_type, ae.occurred_at, ae.actor, ae.note,
                   j.title, j.company, j.status
            FROM application_events ae
            JOIN jobs j ON j.id = ae.job_id
            WHERE ae.occurred_at >= ?
              AND ae.event_type IN ('applied', 'engaged', 'company_rejected',
                                    'withdrawn', 'offer_accepted', 'offer_declined',
                                    'skipped', 'rejected', 'overridden')
            ORDER BY ae.occurred_at DESC
            LIMIT ?
            """,
            (cutoff, limit),
        ).fetchall()

        # Map event_type → the status the job transitioned TO.
        event_to_status: dict[str, str] = {
            "applied": "applied",
            "engaged": "engaged",
            "company_rejected": "company_rejected",
            "withdrawn": "withdrawn",
            "offer_accepted": "offer_accepted",
            "offer_declined": "offer_declined",
            "skipped": "skipped",
            "rejected": "rejected",
            "overridden": "overridden",
        }

        rejection_events = {"rejected", "skipped"}

        # Infer from_status by walking events chronologically per job:
        # each event's "from" is the previous event's "to" for that job.
        # Rows are DESC (newest first), so iterate in reverse for ASC order.
        prev_status: dict[int, str] = {}
        enriched: list[tuple] = []  # (row, from_status, to_status)
        for r in reversed(rows):
            to_status = event_to_status.get(r["event_type"], r["status"] or "")
            from_s = prev_status.get(r["job_id"])
            enriched.append((r, from_s, to_status))
            prev_status[r["job_id"]] = to_status
        enriched.reverse()  # back to DESC for display

        events: list[MovementEvent] = []
        rejection_count = 0
        rejection_breakdown: dict[str, int] = {}

        for r, from_s, to_s in enriched:
            if r["event_type"] in rejection_events:
                rejection_count += 1
                rejection_breakdown[r["event_type"]] = rejection_breakdown.get(r["event_type"], 0) + 1
                continue
            events.append(MovementEvent(
                job_id=r["job_id"],
                job_title=r["title"] or "",
                company=r["company"] or "",
                event_type=r["event_type"],
                from_status=from_s,
                to_status=to_s,
                occurred_at=r["occurred_at"] or "",
                actor=r["actor"] or "",
                note=r["note"],
            ))
        return MovementReport(
            events=events,
            total=len(events),
            rejection_count=rejection_count,
            rejection_breakdown=rejection_breakdown,
        )
    finally:
        db.close()


@router.get("/aging", response_model=AgingReport)
def get_aging():
    """Aging report — how long jobs have been sitting in each post-ready status.

    For each status (applied, engaged, reviewing, interested), computes:
    - count, avg days since last activity, max days, stale count
    """
    settings = get_settings()
    stale_after = settings.lifecycle.stale_after_days if settings.lifecycle else 14

    db = get_connection()
    try:
        statuses = ["reviewing", "interested", "applied", "engaged",
                     "offer_accepted", "offer_declined"]
        buckets: list[AgingBucket] = []

        for status in statuses:
            rows = db.execute(
                """
                SELECT j.id, j.updated_at,
                       COALESCE(
                           (SELECT MAX(ae.occurred_at)
                            FROM application_events ae
                            WHERE ae.job_id = j.id),
                           j.updated_at,
                           j.discovered_at
                       ) as last_activity
                FROM jobs j
                WHERE j.status = ?
                """,
                (status,),
            ).fetchall()

            count = len(rows)
            if count == 0:
                buckets.append(AgingBucket(status=status, count=0))
                continue

            now = datetime.now(UTC)
            days_list: list[float] = []
            for r in rows:
                last = r["last_activity"]
                if last:
                    try:
                        dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                        delta = (now - dt).total_seconds() / 86400.0
                        days_list.append(max(delta, 0.0))
                    except (ValueError, TypeError):
                        days_list.append(0.0)
                else:
                    days_list.append(0.0)

            avg_days = sum(days_list) / count if count else 0.0
            max_days = int(max(days_list)) if days_list else 0
            stale = sum(1 for d in days_list if d >= stale_after)

            buckets.append(AgingBucket(
                status=status,
                count=count,
                avg_days=round(avg_days, 1),
                max_days=max_days,
                stale_count=stale,
            ))

        return AgingReport(buckets=buckets, stale_after_days=stale_after)
    finally:
        db.close()


@router.get("/signal-quality", response_model=SignalQualityReport)
def get_signal_quality():
    """Signal quality report — verdict distribution + calibration summary.

    Shows how AI verdicts (APPLY, CONDITIONAL, MONITOR, SKIP) are distributed
    across analyzed jobs, plus false-positive/false-negative rates from
    calibration data if available.
    """
    db = get_connection()
    try:
        # Verdict distribution from jobs table
        verdict_rows = db.execute(
            """
            SELECT analysis_verdict, COUNT(*) as c
            FROM jobs
            WHERE analysis_verdict IS NOT NULL AND analysis_verdict != ''
            GROUP BY analysis_verdict
            ORDER BY c DESC
            """,
        ).fetchall()

        total = sum(r["c"] for r in verdict_rows)
        verdicts: list[VerdictDistribution] = []
        for r in verdict_rows:
            pct = (r["c"] / total * 100.0) if total > 0 else 0.0
            verdicts.append(VerdictDistribution(
                verdict=r["analysis_verdict"],
                count=r["c"],
                pct=round(pct, 1),
            ))

        apply_count = next((v.count for v in verdicts if v.verdict == "APPLY"), 0)
        skip_count = next((v.count for v in verdicts if v.verdict == "SKIP"), 0)
        apply_rate = (apply_count / total * 100.0) if total > 0 else 0.0
        skip_rate = (skip_count / total * 100.0) if total > 0 else 0.0

        # Calibration summary (best-effort — may not be configured)
        false_pos = 0.0
        false_neg = 0.0
        cal_available = False
        try:
            settings = get_settings()
            if settings.scoring:
                report = build_calibration_report(db, settings.scoring)
                total_decided = report["total_applied"] + report["total_skipped"]
                if total_decided > 0:
                    false_pos = len(report["false_positives"]) / total_decided * 100.0
                    false_neg = len(report["false_negatives"]) / total_decided * 100.0
                cal_available = True
        except Exception:
            logger.exception("Signal-quality calibration data is unavailable")
            warnings = ["Calibration metrics are unavailable."]
        else:
            warnings = []

        return SignalQualityReport(
            total_analyzed=total,
            verdicts=verdicts,
            apply_rate=round(apply_rate, 1),
            skip_rate=round(skip_rate, 1),
            false_positive_pct=round(false_pos, 1),
            false_negative_pct=round(false_neg, 1),
            calibration_available=cal_available,
            partial=bool(warnings),
            warnings=warnings,
        )
    finally:
        db.close()


@router.get("/spend", response_model=SpendReport)
def get_spend():
    """LLM spend report — aggregate token usage and estimated cost.

    Aggregates input/output tokens from job_analyses and resumes tables,
    computes estimated cost using per-model pricing from providers.yml
    and/or auto-fetched pricing from provider APIs (Kilo, OpenRouter),
    and derives cost-per-ready and cost-per-applied metrics.
    """
    settings = get_settings()

    # Build pricing lookup: {(provider, model): (input_per_mtok, output_per_mtok)}
    pricing: dict[tuple[str, str], tuple[float | None, float | None]] = {}
    pricing_configured = False
    # Track which models had YAML pricing vs auto-fetched pricing
    yaml_priced: set[tuple[str, str]] = set()
    auto_priced: set[tuple[str, str]] = set()

    # 1. YAML config pricing (providers.yml)
    for prov in (settings.providers.providers if settings.providers else []):
        for model in prov.models:
            if model.input_price_per_mtok is not None or model.output_price_per_mtok is not None:
                pricing_configured = True
                yaml_priced.add((prov.id, model.id))
            pricing[(prov.id, model.id)] = (
                model.input_price_per_mtok,
                model.output_price_per_mtok,
            )

    # 2. Auto-fetched pricing from model cache (Kilo, OpenRouter, etc.)
    from seeker_os.llm.cache import get_cached_pricing

    # Track fetched_at per provider for staleness detection
    pricing_fetched_at: dict[str, str | None] = {}

    for prov in (settings.providers.providers if settings.providers else []):
        cached = get_cached_pricing(prov.id)
        if not cached:
            continue
        # Read fetched_at from the raw cache file for staleness tracking
        import json as _json
        from seeker_os.llm.cache import _cache_path
        try:
            cache_data = _json.loads(_cache_path(prov.id).read_text())
            pricing_fetched_at[prov.id] = cache_data.get("fetched_at")
        except Exception:
            pass
        for model_id, (auto_in, auto_out) in cached.items():
            key = (prov.id, model_id)
            yaml_in, yaml_out = pricing.get(key, (None, None))
            # Fill in missing pricing from auto-fetched data
            in_price = yaml_in if yaml_in is not None else auto_in
            out_price = yaml_out if yaml_out is not None else auto_out
            if in_price is not None or out_price is not None:
                pricing_configured = True
                if auto_in is not None or auto_out is not None:
                    auto_priced.add(key)
            pricing[key] = (in_price, out_price)

    def _estimate_cost(provider: str, model: str, in_tok: int, out_tok: int) -> float:
        key = (provider, model)
        in_price, out_price = pricing.get(key, (None, None))
        # Fuzzy match: handle version-pinned IDs like 'qwen/qwen3.7-max-20260520'
        # where the cache has the base ID 'qwen/qwen3.7-max'
        if in_price is None and out_price is None:
            for (p, m), (pin, pout) in pricing.items():
                if p != provider:
                    continue
                if model.startswith(m + "-") or m.startswith(model + "-"):
                    in_price, out_price = pin, pout
                    break
        cost = 0.0
        if in_price is not None:
            cost += in_tok / 1_000_000 * in_price
        if out_price is not None:
            cost += out_tok / 1_000_000 * out_price
        return cost

    db = get_connection()
    try:
        ledger_rows = db.execute(
            """
            SELECT COALESCE(actual_provider, requested_provider) AS provider,
                   COALESCE(actual_model, requested_model) AS model,
                   task, COUNT(*) AS calls,
                   SUM(input_tokens) AS in_tok,
                   SUM(output_tokens) AS out_tok,
                   SUM(estimated_cost) AS ledger_cost
            FROM llm_calls
            GROUP BY COALESCE(actual_provider, requested_provider),
                     COALESCE(actual_model, requested_model), task
            """
        ).fetchall()

        # Combine
        by_task: dict[str, dict] = {}
        by_model: dict[tuple[str, str], dict] = {}
        total_calls = 0
        total_in = 0
        total_out = 0
        total_cost = 0.0

        for r in ledger_rows:
            provider_id = r["provider"] or "unknown"
            model_id = r["model"] or "unknown"
            task = r["task"] or "unknown"
            calls = r["calls"] or 0
            in_tok = r["in_tok"] or 0
            out_tok = r["out_tok"] or 0
            cost = r["ledger_cost"] or 0.0

            total_calls += calls
            total_in += in_tok
            total_out += out_tok
            total_cost += cost

            # By task
            if task not in by_task:
                by_task[task] = {"calls": 0, "in": 0, "out": 0, "cost": 0.0}
            by_task[task]["calls"] += calls
            by_task[task]["in"] += in_tok
            by_task[task]["out"] += out_tok
            by_task[task]["cost"] += cost

            # By model
            key = (provider_id, model_id)
            if key not in by_model:
                by_model[key] = {"provider": provider_id, "model": model_id, "calls": 0, "in": 0, "out": 0, "cost": 0.0}
            by_model[key]["calls"] += calls
            by_model[key]["in"] += in_tok
            by_model[key]["out"] += out_tok
            by_model[key]["cost"] += cost

        # Cost-per metrics
        ready_count = db.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE status = 'ready'"
        ).fetchone()["c"]
        applied_count = db.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE status IN ('applied', 'engaged', 'offer_accepted')"
        ).fetchone()["c"]

        cost_per_ready = round(total_cost / ready_count, 4) if ready_count > 0 and total_cost > 0 else None
        cost_per_applied = round(total_cost / applied_count, 4) if applied_count > 0 and total_cost > 0 else None

        # Determine pricing staleness
        stale_threshold_days = settings.providers.pricing_stale_after_days if settings.providers else 30
        pricing_stale = False
        oldest_fetched_at: str | None = None
        now = datetime.now(UTC)
        for prov_id, fetched_at in pricing_fetched_at.items():
            if fetched_at is None:
                continue
            if oldest_fetched_at is None or fetched_at < oldest_fetched_at:
                oldest_fetched_at = fetched_at
            try:
                dt = datetime.fromisoformat(fetched_at.replace("Z", "+00:00"))
                if (now - dt).days > stale_threshold_days:
                    pricing_stale = True
            except (ValueError, TypeError):
                pass

        # Build route-price comparisons: same underlying model available on multiple routes
        # Group by the model id without provider prefix (e.g. "anthropic/claude-opus-4.8" → "claude-opus-4.8")
        # Only consider enabled providers — disabled providers are not valid routing options
        # Deduplicate within a single provider: a gateway like Kilo may list the same base
        # model from multiple upstreams (e.g. anthropic/claude-opus-4.8 and stealth/claude-opus-4.8).
        # These are not independent routes — pick the cheapest entry per provider.
        enabled_provider_ids = {
            p.id for p in (settings.providers.providers if settings.providers else []) if p.enabled
        }
        # {base_model: {prov_id: cheapest route dict}}
        route_map: dict[str, dict[str, dict]] = {}
        for (prov_id, model_id), (in_price, out_price) in pricing.items():
            if prov_id not in enabled_provider_ids:
                continue
            if in_price is None and out_price is None:
                continue
            # Normalize: strip provider prefix if present (e.g. "anthropic/claude-opus-4.8" → "claude-opus-4.8")
            base_model = model_id.split("/")[-1] if "/" in model_id else model_id
            entry = {
                "provider": prov_id,
                "input_price_per_mtok": in_price,
                "output_price_per_mtok": out_price,
            }
            prov_routes = route_map.setdefault(base_model, {})
            existing = prov_routes.get(prov_id)
            if existing is None:
                prov_routes[prov_id] = entry
            else:
                # Keep the cheaper one (by input price, fall back to output)
                old_in = existing.get("input_price_per_mtok") or float("inf")
                new_in = in_price if in_price is not None else float("inf")
                if new_in < old_in:
                    prov_routes[prov_id] = entry

        route_pricing: list[PricingRouteComparison] = []
        for base_model, prov_routes in route_map.items():
            routes = list(prov_routes.values())
            if len(routes) < 2:
                continue
            # Compute max variance on input price
            in_prices = [r["input_price_per_mtok"] for r in routes if r["input_price_per_mtok"] is not None and r["input_price_per_mtok"] > 0]
            if len(in_prices) >= 2:
                lo, hi = min(in_prices), max(in_prices)
                variance = round((hi - lo) / lo * 100.0, 1) if lo > 0 else 0.0
            else:
                variance = 0.0
            if variance > 20.0:
                route_pricing.append(PricingRouteComparison(
                    model=base_model,
                    routes=routes,
                    variance_pct=variance,
                ))
        route_pricing.sort(key=lambda r: r.variance_pct, reverse=True)

        return SpendReport(
            total_calls=total_calls,
            total_input_tokens=total_in,
            total_output_tokens=total_out,
            total_estimated_cost=round(total_cost, 4),
            pricing_configured=pricing_configured,
            by_task=[
                SpendByTask(
                    task=t,
                    calls=d["calls"],
                    input_tokens=d["in"],
                    output_tokens=d["out"],
                    estimated_cost=round(d["cost"], 4),
                )
                for t, d in sorted(by_task.items(), key=lambda x: x[1]["cost"], reverse=True)
            ],
            by_model=[
                SpendByModel(
                    provider=d["provider"],
                    model=d["model"],
                    calls=d["calls"],
                    input_tokens=d["in"],
                    output_tokens=d["out"],
                    estimated_cost=round(d["cost"], 4),
                    input_price_per_mtok=pricing.get((d["provider"], d["model"]), (None, None))[0],
                    output_price_per_mtok=pricing.get((d["provider"], d["model"]), (None, None))[1],
                    pricing_source=(
                        "yaml+auto" if (d["provider"], d["model"]) in yaml_priced and (d["provider"], d["model"]) in auto_priced
                        else "yaml" if (d["provider"], d["model"]) in yaml_priced
                        else "auto" if (d["provider"], d["model"]) in auto_priced
                        else ""
                    ),
                    pricing_fetched_at=pricing_fetched_at.get(d["provider"]),
                )
                for d in sorted(by_model.values(), key=lambda x: x["cost"], reverse=True)
            ],
            cost_per_ready=cost_per_ready,
            cost_per_applied=cost_per_applied,
            pricing_fetched_at=oldest_fetched_at,
            pricing_stale=pricing_stale,
            pricing_stale_after_days=stale_threshold_days,
            route_pricing=route_pricing,
            partial=True,
            warnings=["Usage before the LLM ledger activation is not included."],
        )
    finally:
        db.close()
