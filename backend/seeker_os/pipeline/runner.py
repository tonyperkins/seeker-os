"""Pipeline runner — orchestrates Tier 1→5."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
import sqlite3

from seeker_os.config import Settings
from seeker_os.database import get_connection, json_encode, json_decode
from seeker_os.discovery.cache import DiskCache
from seeker_os.discovery.engine import fetch_all_queries
from seeker_os.discovery.sources.registry import build_adapters
from seeker_os.filtering.hard_filters import apply_filters
from seeker_os.scoring.engine import score_job
from seeker_os.dedup.layers import (
    check_duplicate,
    check_content_duplicate,
    register_keys,
    register_content_hash,
    url_hash,
)
from seeker_os.discovery.ats_fetch import fetch_jd
from seeker_os.crossref.jobsearch_repo import sync_repo, check_cross_reference
from seeker_os.models import JobCard, PipelineProgressEvent, PipelineRunResult
from seeker_os.events import record_event, transition_status, EventType, Actor

logger = logging.getLogger(__name__)


def _insert_job(db: sqlite3.Connection, job: JobCard, run_id: str | None = None) -> int:
    """Insert a new job into the DB. Returns the job ID."""
    now = datetime.now(timezone.utc).isoformat()
    uh = url_hash(job.apply_url)

    cursor = db.execute(
        """
        INSERT INTO jobs (
            source_id, source_job_id, ats_source, ats_board_token, ats_job_id,
            apply_url, url_hash,
            title, core_title, company, company_homepage,
            location, workplace_type, workplace_countries, seniority_level,
            commitment, comp_min, comp_max, comp_currency, comp_source,
            technical_tools, requirements_summary, date_posted, role_type,
            status, tier_passed, discovered_at, discovered_query, updated_at, is_pinned,
            detail_url, run_id
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'discovered', 1, ?, ?, ?, ?, ?, ?)
        """,
        (
            job.source_id, job.source_job_id, job.ats_source, job.ats_board_token, job.ats_job_id,
            job.apply_url, uh,
            job.title, job.core_title, job.company, job.company_homepage,
            job.location, job.workplace_type, json_encode(job.workplace_countries), job.seniority_level,
            json_encode(job.commitment), job.comp_min, job.comp_max, job.comp_currency, job.comp_source,
            json_encode(job.technical_tools), job.requirements_summary, job.date_posted, job.role_type,
            now, job.discovered_query, now, job.is_pinned,
            job.detail_url,
            run_id,
        ),
    )
    job_id = cursor.lastrowid
    record_event(db, job_id, EventType.DISCOVERED, Actor.SYSTEM)
    return job_id


def _get_job_row(db: sqlite3.Connection, job_id: int) -> sqlite3.Row | None:
    return db.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()


def run_pipeline(
    settings: Settings,
    queries: list[str] | None = None,
    tiers: list[int] | None = None,
    dry_run: bool = False,
    progress_cb: Callable[[PipelineProgressEvent], None] | None = None,
    force_full_pull: bool = False,
) -> PipelineRunResult:
    """Run the full pipeline (or specific tiers).

    Tier 1: Fetch cards from source adapters
    Tier 2: Card-level hard filters
    Tier 3: Full JD fetch
    Tier 4: Scoring
    Tier 5: Ranking + cross-reference + report

    If progress_cb is provided, it's called with PipelineProgressEvent objects
    at each step of the pipeline for real-time progress tracking.

    When force_full_pull is False and a query has search_query set, the adapter
    requests only jobs posted since the query's last_run_at (incremental search).
    When force_full_pull is True, no date filter is applied (full pull).
    """

    def _emit(step: str, label: str, status: str, current: int = 0, total: int = 0, detail: str = ""):
        if progress_cb:
            progress_cb(PipelineProgressEvent(
                step=step, step_label=label, status=status,
                current=current, total=total, detail=detail,
                cards_fetched=result.cards_fetched, cards_new=result.cards_new,
                duplicates_skipped=result.duplicates_skipped,
                tier2_passed=result.tier2_passed, tier2_rejected=result.tier2_rejected,
                tier3_fetched=result.tier3_fetched, tier3_failed=result.tier3_failed,
                tier4_scored=result.tier4_scored, tier4_rejected=result.tier4_rejected,
                tier4_hard_rejected=result.tier4_hard_rejected,
                tier5_ready=result.tier5_ready,
            ))
    now = datetime.now(timezone.utc)
    db = get_connection()
    date_part = now.strftime("%m%d")
    existing = db.execute(
        "SELECT run_id FROM pipeline_runs WHERE run_id LIKE ? ORDER BY run_id DESC",
        (f"{date_part}-%",),
    ).fetchall()
    seq = 1
    if existing:
        last_seq = existing[0]["run_id"].split("-")[-1]
        try:
            seq = int(last_seq) + 1
        except ValueError:
            pass
    run_id = f"{date_part}-{seq:02d}"
    result = PipelineRunResult(run_id=run_id)
    tier_set = set(tiers) if tiers else {1, 2, 3, 4, 5}

    cache = DiskCache(Path("data/cache"), ttl_hours=settings.sources.sources[0].cache_ttl_hours if settings.sources else 6)

    # Get source_map from the first enabled source (hiring.cafe)
    source_map = {}
    if settings.sources:
        for src in settings.sources.sources:
            if src.enabled and src.source_map:
                source_map = src.source_map
                break

    # -----------------------------------------------------------------------
    # Tier 1: Discovery
    # -----------------------------------------------------------------------
    if 1 in tier_set:
        print("\nTier 1: Discovery")
        adapters = build_adapters(settings.sources, cache) if settings.sources else {}

        # Load queries from DB (UI writes here) with YAML fallback
        db_queries = db.execute(
            "SELECT source_id, query_slug, label, commitment_filter, max_pages, enabled, search_query "
            "FROM search_queries ORDER BY id"
        ).fetchall()
        if db_queries:
            from seeker_os.config import QueryConfig
            all_queries = [
                QueryConfig(
                    source_id=r["source_id"] or "hiring_cafe",
                    slug=r["query_slug"],
                    label=r["label"] or r["query_slug"],
                    commitment=r["commitment_filter"] or "full_time",
                    max_pages=r["max_pages"] or 1,
                    enabled=bool(r["enabled"]),
                    search_query=r["search_query"] if "search_query" in r.keys() else None,
                )
                for r in db_queries
            ]
        else:
            all_queries = settings.queries.queries if settings.queries else []
        if queries:
            all_queries = [q for q in all_queries if q.slug in queries]

        from seeker_os.models import SourceQuery
        source_queries: list[SourceQuery] = []
        for q in all_queries:
            posted_within_days: int | None = None
            if q.search_query and not force_full_pull:
                # Compute days since last run for incremental search
                row = db.execute(
                    "SELECT last_run_at FROM search_queries WHERE query_slug=? AND source_id=?",
                    (q.slug, q.source_id),
                ).fetchone()
                last_run = row["last_run_at"] if row else None
                if last_run:
                    try:
                        last_dt = datetime.fromisoformat(last_run)
                        if last_dt.tzinfo is None:
                            last_dt = last_dt.replace(tzinfo=timezone.utc)
                        delta = now - last_dt
                        posted_within_days = max(1, delta.days)
                    except (ValueError, TypeError):
                        pass  # Invalid timestamp → no date filter

            # Map FilterConfig → server-side filter hints (Phase 2)
            # Only set when the query uses structured search (search_query present),
            # since slug-based URLs don't support server-side filtering.
            sq_workplace_types: list[str] | None = None
            sq_commitments: list[str] | None = None
            sq_seniority_levels: list[str] | None = None
            sq_role_types: list[str] | None = None
            if q.search_query and settings.filters:
                fc = settings.filters.filters
                if fc.remote_only:
                    sq_workplace_types = ["Remote"]
                if fc.commitment_required:
                    # Map our config value to hiring.cafe's format
                    commitment_map = {
                        "full_time": "Full Time",
                        "full-time": "Full Time",
                        "part_time": "Part Time",
                        "part-time": "Part Time",
                        "contract": "Contract",
                    }
                    mapped = commitment_map.get(fc.commitment_required.lower(), fc.commitment_required)
                    sq_commitments = [mapped]
                if fc.seniority_floor:
                    sq_seniority_levels = list(fc.seniority_floor)
                # role_types: no config field yet, leave as None

            source_queries.append(SourceQuery(
                source_id=q.source_id,
                slug=q.slug,
                label=q.label,
                commitment=q.commitment,
                max_pages=q.max_pages,
                enabled=q.enabled,
                search_query=q.search_query,
                posted_within_days=posted_within_days,
                workplace_types=sq_workplace_types,
                commitments=sq_commitments,
                seniority_levels=sq_seniority_levels,
                role_types=sq_role_types,
            ))

        enabled_count = sum(1 for sq in source_queries if sq.enabled)
        _emit("discovery", "Discovery", "started", detail=f"Fetching from {enabled_count} queries…")
        cards = fetch_all_queries(source_queries, adapters, cache)
        result.cards_fetched = len(cards)
        _emit("discovery", "Discovery", "in_progress", total=len(cards), detail=f"Fetched {len(cards)} cards")

        if dry_run:
            print(f"  [dry-run] {len(cards)} cards fetched, not inserting to DB")
        else:
            # Dedup check (layers 1-2) before insert
            for i, card in enumerate(cards):
                dedup = check_duplicate(card, db, source_map)
                if dedup.is_duplicate:
                    result.duplicates_skipped += 1
                    # Backfill detail_url for existing jobs if the new card has one
                    # and the existing job doesn't (e.g. jobs discovered before the
                    # detail_url feature was added)
                    if card.detail_url and dedup.matched_job_id:
                        existing = db.execute(
                            "SELECT detail_url FROM jobs WHERE id=?", (dedup.matched_job_id,)
                        ).fetchone()
                        if existing and not existing["detail_url"]:
                            db.execute(
                                "UPDATE jobs SET detail_url=?, updated_at=? WHERE id=?",
                                (card.detail_url, datetime.now(timezone.utc).isoformat(), dedup.matched_job_id),
                            )
                    continue

                job_id = _insert_job(db, card, run_id=run_id)
                register_keys(job_id, card, db, source_map)
                result.cards_new += 1

                if (i + 1) % 10 == 0 or i == len(cards) - 1:
                    _emit("discovery", "Discovery", "in_progress",
                          current=i + 1, total=len(cards),
                          detail=f"Inserted {result.cards_new} new, skipped {result.duplicates_skipped} duplicates")

            db.commit()

            # Update last_run_at for each query that was run
            run_timestamp = datetime.now(timezone.utc).isoformat()
            for sq in source_queries:
                db.execute(
                    "UPDATE search_queries SET last_run_at=? WHERE query_slug=? AND source_id=?",
                    (run_timestamp, sq.slug, sq.source_id),
                )
            db.commit()

            print(f"  Total fetched: {result.cards_fetched} cards")
            print(f"  New (after dedup): {result.cards_new}")
            print(f"  Duplicates skipped: {result.duplicates_skipped}")
            _emit("discovery", "Discovery", "completed",
                  total=len(cards),
                  detail=f"{result.cards_new} new, {result.duplicates_skipped} duplicates")

    # -----------------------------------------------------------------------
    # Tier 2: Card-Level Hard Filters
    # -----------------------------------------------------------------------
    if 2 in tier_set and not dry_run:
        print("\nTier 2: Card-Level Filters")
        jobs = db.execute(
            "SELECT * FROM jobs WHERE status='discovered' AND tier_passed=1"
        ).fetchall()
        _emit("filtering", "Filtering", "started", total=len(jobs),
              detail=f"Filtering {len(jobs)} jobs…")

        for i, row in enumerate(jobs):
            # Reconstruct JobCard-like from DB row
            card = JobCard(
                source_id=row["source_id"] or "",
                source_job_id=row["source_job_id"] or "",
                ats_source=row["ats_source"],
                ats_board_token=row["ats_board_token"],
                ats_job_id=row["ats_job_id"],
                apply_url=row["apply_url"] or "",
                title=row["title"] or "",
                core_title=row["core_title"] or "",
                company=row["company"] or "",
                company_homepage=row["company_homepage"],
                location=row["location"] or "",
                workplace_type=row["workplace_type"] or "",
                workplace_countries=json_decode(row["workplace_countries"]) or [],
                seniority_level=row["seniority_level"],
                commitment=json_decode(row["commitment"]) or [],
                comp_min=row["comp_min"],
                comp_max=row["comp_max"],
                comp_currency=row["comp_currency"],
                technical_tools=json_decode(row["technical_tools"]) or [],
                requirements_summary=row["requirements_summary"] or "",
                date_posted=row["date_posted"] or "",
                role_type=row["role_type"],
                is_pinned=bool(row["is_pinned"]),
                discovered_query=row["discovered_query"] or "",
            )

            filter_result = apply_filters(
                card, settings.profile, settings.filters.filters, settings.filters.title_filters,
            )

            if filter_result.passed:
                transition_status(
                    db, row["id"], "filtered", EventType.FILTER_PASSED, Actor.SYSTEM,
                    extra_sets={"tier_passed": 2},
                )
                result.tier2_passed += 1
            else:
                transition_status(
                    db, row["id"], "rejected", EventType.FILTER_REJECTED, Actor.SYSTEM,
                    extra_sets={"reject_reason": filter_result.reason},
                    metadata={"reason": filter_result.reason},
                )
                result.tier2_rejected += 1
                result.rejection_reasons[filter_result.reason] = (
                    result.rejection_reasons.get(filter_result.reason, 0) + 1
                )

            if (i + 1) % 10 == 0 or i == len(jobs) - 1:
                _emit("filtering", "Filtering", "in_progress",
                      current=i + 1, total=len(jobs),
                      detail=f"{result.tier2_passed} passed, {result.tier2_rejected} rejected")

        db.commit()
        print(f"  Passed: {result.tier2_passed}")
        print(f"  Rejected: {result.tier2_rejected}")
        for reason, count in sorted(result.rejection_reasons.items(), key=lambda x: -x[1]):
            print(f"    - {reason}: {count}")
        _emit("filtering", "Filtering", "completed",
              total=len(jobs),
              detail=f"{result.tier2_passed} passed, {result.tier2_rejected} rejected")

    # -----------------------------------------------------------------------
    # Tier 3: Full JD Fetch
    # -----------------------------------------------------------------------
    if 3 in tier_set and not dry_run:
        print("\nTier 3: JD Fetch")
        # Process new jobs (pending) AND retry previously failed JD fetches.
        # Failed jobs have status='rejected' from the prior failure — we reset
        # them back to 'filtered' so they can flow through the pipeline again.
        retry_jobs = db.execute(
            "SELECT * FROM jobs WHERE tier_passed=2 AND jd_fetch_status='failed' AND status='rejected'"
        ).fetchall()
        if retry_jobs:
            print(f"  Retrying {len(retry_jobs)} previously failed JD fetches")
            for row in retry_jobs:
                transition_status(
                    db, row["id"], "filtered", EventType.JD_FETCH_RETRY, Actor.SYSTEM,
                    extra_sets={"jd_fetch_status": "pending", "reject_reason": None},
                )
            db.commit()

        jobs = db.execute(
            "SELECT * FROM jobs WHERE status='filtered' AND tier_passed=2 AND jd_fetch_status='pending'"
        ).fetchall()
        _emit("jd_fetch", "JD Fetch", "started", total=len(jobs),
              detail=f"Fetching JDs for {len(jobs)} jobs…")

        # Get user_agent and delay from sources config
        user_agent = "Mozilla/5.0"
        jd_delay = 2.0
        if settings.sources:
            for src in settings.sources.sources:
                if src.enabled:
                    user_agent = src.user_agent
                    jd_delay = src.jd_fetch_delay_seconds
                    break

        for i, row in enumerate(jobs):
            jd_result = fetch_jd(
                job_id=row["id"],
                ats_source=row["ats_source"],
                ats_board_token=row["ats_board_token"],
                ats_job_id=row["ats_job_id"],
                apply_url=row["apply_url"],
                user_agent=user_agent,
                delay=jd_delay,
                detail_url=row["detail_url"] if "detail_url" in row.keys() else None,
            )

            if jd_result.status == "fetched":
                transition_status(
                    db, row["id"], "jd_fetched", EventType.JD_FETCHED, Actor.SYSTEM,
                    extra_sets={
                        "jd_full": jd_result.jd_text,
                        "jd_fetch_status": "fetched",
                        "tier_passed": 3,
                    },
                )
                result.tier3_fetched += 1

                # Run dedup layers 3 (content hash) after JD is available
                content_dedup = check_content_duplicate(row["id"], jd_result.jd_text, db)
                if content_dedup.is_duplicate:
                    transition_status(
                        db, row["id"], "duplicate_flagged", EventType.DUPLICATE_FLAGGED, Actor.SYSTEM,
                    )
                else:
                    register_content_hash(row["id"], jd_result.jd_text, db)

            else:
                transition_status(
                    db, row["id"], "rejected", EventType.JD_FETCH_FAILED, Actor.SYSTEM,
                    extra_sets={
                        "jd_fetch_status": "failed",
                        "reject_reason": f"JD fetch failed: {jd_result.error}",
                    },
                    metadata={"error": jd_result.error},
                )
                result.tier3_failed += 1

            # Commit per job: each JD fetch is independent, so a crash mid-tier
            # keeps completed fetches instead of rolling back the whole tier.
            # Re-running picks up the still-pending / newly-failed jobs.
            db.commit()

            _emit("jd_fetch", "JD Fetch", "in_progress",
                  current=i + 1, total=len(jobs),
                  detail=f"{result.tier3_fetched} fetched, {result.tier3_failed} failed — {row['title'][:40]}")

        db.commit()

        print(f"  Fetched: {result.tier3_fetched}")
        print(f"  Failed: {result.tier3_failed}")
        _emit("jd_fetch", "JD Fetch", "completed",
              total=len(jobs),
              detail=f"{result.tier3_fetched} fetched, {result.tier3_failed} failed")

    # -----------------------------------------------------------------------
    # Tier 4: Scoring
    # -----------------------------------------------------------------------
    if 4 in tier_set and not dry_run:
        print("\nTier 4: Scoring")
        jobs = db.execute(
            "SELECT * FROM jobs WHERE status='jd_fetched' AND tier_passed=3 AND score IS NULL"
        ).fetchall()
        _emit("scoring", "Scoring", "started", total=len(jobs),
              detail=f"Scoring {len(jobs)} jobs…")

        for i, row in enumerate(jobs):
            score_result = score_job(
                title=row["title"] or "",
                jd_text=row["jd_full"] or "",
                location=row["location"] or "",
                company=row["company"] or "",
                rubric=settings.scoring,
                profile=settings.profile,
                comp_min=row["comp_min"],
                comp_max=row["comp_max"],
                workplace_type=row["workplace_type"],
                seniority_level=row["seniority_level"],
                comp_source=row["comp_source"] if "comp_source" in row.keys() else "none",
                never_claim=settings.identity.never_claim if settings.identity else None,
            )

            if score_result.hard_reject:
                transition_status(
                    db, row["id"], "rejected", EventType.SCORED_REJECTED, Actor.SYSTEM,
                    extra_sets={
                        "score": 0,
                        "score_reasons": json_encode(score_result.reasons),
                        "score_gaps": json_encode(score_result.gaps),
                        "score_modifiers": json_encode(score_result.fired_modifiers),
                        "reject_reason": score_result.reject_reason,
                    },
                )
                result.tier4_hard_rejected += 1
            elif score_result.score >= settings.scoring.post_threshold:
                transition_status(
                    db, row["id"], "ready", EventType.SCORED_READY, Actor.SYSTEM,
                    extra_sets={
                        "tier_passed": 4,
                        "score": score_result.score,
                        "score_reasons": json_encode(score_result.reasons),
                        "score_gaps": json_encode(score_result.gaps),
                        "score_modifiers": json_encode(score_result.fired_modifiers),
                    },
                )
                result.tier4_scored += 1
            else:
                transition_status(
                    db, row["id"], "rejected", EventType.SCORED_REJECTED, Actor.SYSTEM,
                    extra_sets={
                        "score": score_result.score,
                        "score_reasons": json_encode(score_result.reasons),
                        "score_gaps": json_encode(score_result.gaps),
                        "score_modifiers": json_encode(score_result.fired_modifiers),
                        "reject_reason": "score below threshold",
                    },
                )
                result.tier4_rejected += 1

            _emit("scoring", "Scoring", "in_progress",
                  current=i + 1, total=len(jobs),
                  detail=f"{result.tier4_scored} passed, {result.tier4_rejected + result.tier4_hard_rejected} rejected — {row['title'][:40]}")

        db.commit()
        print(f"  Scored ≥{settings.scoring.post_threshold}: {result.tier4_scored}")
        print(f"  Scored <{settings.scoring.post_threshold}: {result.tier4_rejected}")
        print(f"  Hard rejected: {result.tier4_hard_rejected}")
        _emit("scoring", "Scoring", "completed",
              total=len(jobs),
              detail=f"{result.tier4_scored} passed, {result.tier4_rejected + result.tier4_hard_rejected} rejected")

    # -----------------------------------------------------------------------
    # Tier 5: Ranking + Cross-reference + Report
    # -----------------------------------------------------------------------
    if 5 in tier_set and not dry_run:
        print("\nTier 5: Ranking & Report")
        _emit("ranking", "Ranking", "started", detail="Applying per-company cap and cross-referencing…")

        # Per-company cap — only applies to jobs from this run
        cap = settings.scoring.per_company_cap
        ready_jobs = db.execute(
            "SELECT * FROM jobs WHERE status='ready' AND tier_passed=4 AND run_id=? ORDER BY score DESC, comp_max DESC, date_posted DESC",
            (run_id,)
        ).fetchall()

        # Group by company and apply cap
        company_counts: dict[str, int] = {}
        for row in ready_jobs:
            company = row["company"] or "Unknown"
            company_counts[company] = company_counts.get(company, 0) + 1
            if company_counts[company] > cap:
                transition_status(
                    db, row["id"], "capped", EventType.CAPPED, Actor.SYSTEM,
                )
                result.tier5_capped += 1

        db.commit()

        # Cross-reference — runs on all ready jobs (not just this run)
        if settings.profile and settings.profile.cross_reference.auto_pull:
            sync_repo(settings.profile.cross_reference.repo_path)

        all_ready_jobs = db.execute(
            "SELECT * FROM jobs WHERE status='ready' ORDER BY score DESC, comp_max DESC, date_posted DESC"
        ).fetchall()

        run_job_ids = {r["id"] for r in ready_jobs}
        for row in all_ready_jobs:
            if settings.profile:
                cross_ref = check_cross_reference(
                    title=row["title"] or "",
                    company=row["company"] or "",
                    repo_path=settings.profile.cross_reference.repo_path,
                )
                if cross_ref.matched:
                    db.execute(
                        "UPDATE jobs SET cross_ref_status=?, cross_ref_date=?, cross_ref_score=? WHERE id=?",
                        (cross_ref.prior_status, cross_ref.prior_date, cross_ref.prior_score, row["id"]),
                    )
                    if row["id"] in run_job_ids:
                        result.cross_ref_matches += 1

        db.commit()
        result.tier5_ready = len(ready_jobs) - result.tier5_capped
        print(f"  Ready for review: {result.tier5_ready}")
        print(f"  Capped (per-company): {result.tier5_capped}")
        print(f"  Cross-ref matches: {result.cross_ref_matches}")
        _emit("ranking", "Ranking", "completed",
              detail=f"{result.tier5_ready} ready, {result.tier5_capped} capped, {result.cross_ref_matches} cross-ref matches")

    # -----------------------------------------------------------------------
    # Auto-analysis (post-scoring, opt-in via scoring_rubric.yml auto_analysis)
    # -----------------------------------------------------------------------
    if (
        not dry_run
        and 4 in tier_set
        and settings.scoring is not None
        and settings.scoring.auto_analysis.enabled
    ):
        _emit("analysis", "Auto-Analysis", "started",
              detail="Analyzing unanalyzed high-scoring jobs…")
        try:
            from seeker_os.analysis.auto_policy import run_auto_analysis
            auto_result = run_auto_analysis(settings, db)
            print(f"\nAuto-analysis: {auto_result['analyzed']} analyzed, "
                  f"{auto_result['failed']} failed "
                  f"(of {auto_result['candidates']} candidates)")
            _emit("analysis", "Auto-Analysis", "completed",
                  total=auto_result["candidates"],
                  detail=f"{auto_result['analyzed']} analyzed, {auto_result['failed']} failed")
        except Exception:
            # Auto-analysis is best-effort enrichment — never fail the run.
            logger.exception("Auto-analysis step failed")
            _emit("analysis", "Auto-Analysis", "completed", detail="failed — see logs")

    # Record pipeline run
    if not dry_run:
        db.execute(
            """
            INSERT INTO pipeline_runs (run_id, started_at, completed_at, cards_fetched, cards_new, cards_survived_tier2, jds_fetched, jobs_scored, jobs_ready, status)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'completed')
            """,
            (
                run_id,
                datetime.now(timezone.utc).isoformat(),
                datetime.now(timezone.utc).isoformat(),
                result.cards_fetched, result.cards_new, result.tier2_passed,
                result.tier3_fetched, result.tier4_scored, result.tier5_ready,
            ),
        )
        db.commit()

    db.close()
    return result
