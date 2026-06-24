"""CLI entry point for Seeker OS.

Commands:
  run          — full pipeline (or specific tiers/queries)
  report       — re-generate report from DB
  stats        — pipeline stats
  dedup-check  — show duplicate stats
  sync-config  — sync yml files to DB
"""

from __future__ import annotations

import sys
import argparse
from datetime import datetime, timezone

from rich.console import Console
from rich.table import Table

from seeker_os.config import Settings
from seeker_os.database import get_connection, run_migrations
from seeker_os.pipeline.runner import run_pipeline

console = Console()


def cmd_run(args: argparse.Namespace) -> None:
    """Run the pipeline."""
    settings = Settings()
    tiers = [int(t) for t in args.tiers.split(",")] if args.tiers else None
    queries = args.queries.split(",") if args.queries else None

    console.print(f"\n[bold cyan]Seeker OS — Pipeline Run {datetime.now().strftime('%Y-%m-%d %H:%M')}[/bold cyan]")

    result = run_pipeline(settings, queries=queries, tiers=tiers, dry_run=args.dry_run)

    # Summary
    console.print(f"\n[bold green]Run complete. {result.tier5_ready} jobs ready for review.[/bold green]")
    console.print("Use 'python -m seeker_os.main report' to re-generate this report.")


def cmd_report(args: argparse.Namespace) -> None:
    """Re-generate report from DB."""
    db = get_connection()
    limit = args.top or 30

    jobs = db.execute(
        """
        SELECT * FROM jobs WHERE status='ready'
        ORDER BY score DESC, comp_max DESC, date_posted DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()

    if not jobs:
        console.print("[yellow]No jobs ready for review. Run the pipeline first.[/yellow]")
        return

    table = Table(title=f"Top Matches ({len(jobs)} jobs ready)", show_lines=True)
    table.add_column("Rank", style="dim", width=4)
    table.add_column("Score", style="bold", width=6)
    table.add_column("Title", width=35)
    table.add_column("Company", width=18)
    table.add_column("Comp", width=15)
    table.add_column("Cross-Ref", width=12)

    for i, row in enumerate(jobs, 1):
        comp_str = ""
        if row["comp_min"] and row["comp_max"]:
            comp_str = f"${row['comp_min']//1000}k-${row['comp_max']//1000}k"
        elif row["comp_max"]:
            comp_str = f"up to ${row['comp_max']//1000}k"

        cross_ref = ""
        if row["cross_ref_status"]:
            cross_ref = f"⚠ {row['cross_ref_status']}"

        table.add_row(
            str(i),
            f"{row['score']:.1f}" if row["score"] else "?",
            row["title"] or "",
            row["company"] or "",
            comp_str,
            cross_ref,
        )

    console.print(table)
    db.close()


def cmd_stats(args: argparse.Namespace) -> None:
    """Show pipeline stats."""
    db = get_connection()

    console.print("\n[bold cyan]Seeker OS — Database Stats[/bold cyan]\n")

    # Total counts by status
    statuses = db.execute(
        "SELECT status, COUNT(*) as count FROM jobs GROUP BY status ORDER BY count DESC"
    ).fetchall()

    total = sum(r["count"] for r in statuses)
    console.print(f"  Total jobs: {total:,}")

    for r in statuses:
        console.print(f"    {r['status']:25s}  {r['count']:>6,}")

    # By tier
    console.print("\n  [bold]By tier passed:[/bold]")
    tiers = db.execute(
        "SELECT tier_passed, COUNT(*) as count FROM jobs GROUP BY tier_passed ORDER BY tier_passed"
    ).fetchall()
    for r in tiers:
        console.print(f"    Tier {r['tier_passed']}: {r['count']:,}")

    # By ATS source
    console.print("\n  [bold]By source ATS:[/bold]")
    sources = db.execute(
        "SELECT ats_source, COUNT(*) as count FROM jobs GROUP BY ats_source ORDER BY count DESC"
    ).fetchall()
    for r in sources:
        console.print(f"    {r['ats_source'] or 'unknown':25s}  {r['count']:>6,}")

    # Pipeline runs
    runs = db.execute(
        "SELECT COUNT(*) as count, MAX(completed_at) as last_run FROM pipeline_runs"
    ).fetchone()
    console.print(f"\n  Pipeline runs: {runs['count']}")
    if runs["last_run"]:
        console.print(f"  Last run: {runs['last_run']}")

    db.close()


def cmd_dedup_check(args: argparse.Namespace) -> None:
    """Show dedup stats."""
    db = get_connection()

    console.print("\n[bold cyan]Seeker OS — Dedup Stats[/bold cyan]\n")

    # By key type
    key_types = db.execute(
        "SELECT key_type, COUNT(*) as count FROM dedup_registry GROUP BY key_type ORDER BY count DESC"
    ).fetchall()

    if not key_types:
        console.print("  No dedup keys registered yet.")
    else:
        for r in key_types:
            console.print(f"  {r['key_type']:25s}  {r['count']:>6,}")

    # Duplicate-flagged jobs
    dupes = db.execute(
        "SELECT COUNT(*) as count FROM jobs WHERE status='duplicate_flagged'"
    ).fetchone()
    console.print(f"\n  Duplicate-flagged jobs: {dupes['count']}")

    db.close()


def cmd_sync_config(args: argparse.Namespace) -> None:
    """Sync YAML config files to DB."""
    console.print("\n[bold cyan]Syncing config to DB...[/bold cyan]")
    settings = Settings()

    db = get_connection()
    now = datetime.now(timezone.utc).isoformat()

    # Sync queries
    if settings.queries:
        for q in settings.queries.queries:
            db.execute(
                """
                INSERT OR REPLACE INTO search_queries
                (source_id, query_slug, label, commitment_filter, max_pages, enabled, notes)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (q.source_id, q.slug, q.label, q.commitment, q.max_pages, q.enabled, "synced from queries.yml"),
            )
        db.commit()
        console.print(f"  Synced {len(settings.queries.queries)} queries")

    # Sync filters to settings table
    if settings.filters:
        import json
        filters_data = settings.filters.model_dump()
        db.execute(
            "INSERT OR REPLACE INTO settings (key, value, updated_at) VALUES ('filters', ?, ?)",
            (json.dumps(filters_data, default=str), now),
        )
        db.commit()
        console.print("  Synced filters")

    db.close()
    console.print("[bold green]Config sync complete.[/bold green]")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        prog="seeker_os",
        description="Seeker OS — structured job search pipeline",
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # run
    run_parser = subparsers.add_parser("run", help="Run the pipeline")
    run_parser.add_argument("--tiers", type=str, help="Comma-separated tier numbers (e.g. 1,2)")
    run_parser.add_argument("--queries", type=str, help="Comma-separated query slugs")
    run_parser.add_argument("--dry-run", action="store_true", help="No DB writes, just report")
    run_parser.set_defaults(func=cmd_run)

    # report
    report_parser = subparsers.add_parser("report", help="Re-generate report from DB")
    report_parser.add_argument("--top", type=int, default=30, help="Top N jobs to show")
    report_parser.add_argument("--format", type=str, default="table", choices=["table", "md"])
    report_parser.set_defaults(func=cmd_report)

    # stats
    stats_parser = subparsers.add_parser("stats", help="Pipeline stats")
    stats_parser.set_defaults(func=cmd_stats)

    # dedup-check
    dedup_parser = subparsers.add_parser("dedup-check", help="Show duplicate stats")
    dedup_parser.set_defaults(func=cmd_dedup_check)

    # sync-config
    sync_parser = subparsers.add_parser("sync-config", help="Sync yml files to DB")
    sync_parser.set_defaults(func=cmd_sync_config)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Ensure DB is migrated
    run_migrations()

    args.func(args)


if __name__ == "__main__":
    main()
