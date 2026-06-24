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

console = Console(width=120)


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

    table = Table(title=f"Top Matches ({len(jobs)} jobs ready)", show_lines=True, expand=True)
    table.add_column("#", style="dim", width=3)
    table.add_column("Score", style="bold green", width=6, justify="right")
    table.add_column("Title", width=40)
    table.add_column("Company", width=20)
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


def cmd_models(args: argparse.Namespace) -> None:
    """LLM model management commands."""
    from seeker_os.config import Settings
    from seeker_os.llm.router import ModelRouter
    from seeker_os.llm.cache import get_cached_models, save_cached_models

    settings = Settings()

    if not settings.providers:
        console.print("[red]No providers configured (config/providers.yml missing)[/red]")
        return

    router = ModelRouter(settings)

    if args.models_command == "list":
        models = router.list_all_models(provider_id=args.provider)
        if not models:
            console.print("[yellow]No models found.[/yellow]")
            return

        from rich.table import Table
        table = Table(title="Available Models")
        table.add_column("ID", style="cyan")
        table.add_column("Label")
        table.add_column("Provider", style="green")
        table.add_column("Tags", style="yellow")
        table.add_column("Source", style="dim")
        table.add_column("Available")

        for m in models:
            table.add_row(
                m.id,
                m.label,
                m.provider_id,
                ", ".join(m.tags) if m.tags else "-",
                m.source,
                "✓" if m.available else "✗",
            )
        console.print(table)

    elif args.models_command == "search":
        query = args.query.lower()
        models = router.list_all_models(provider_id=args.provider)
        filtered = [
            m for m in models
            if query in m.id.lower() or query in m.label.lower()
        ]
        if args.tag:
            filtered = [m for m in filtered if args.tag in m.tags]

        if not filtered:
            console.print(f"[yellow]No models matching '{args.query}'[/yellow]")
            return

        from rich.table import Table
        table = Table(title=f"Models matching '{args.query}'")
        table.add_column("ID", style="cyan")
        table.add_column("Label")
        table.add_column("Provider", style="green")
        table.add_column("Tags", style="yellow")

        for m in filtered:
            table.add_row(m.id, m.label, m.provider_id, ", ".join(m.tags) if m.tags else "-")
        console.print(table)

    elif args.models_command == "fetch":
        providers = router.get_available_providers()
        if args.provider:
            providers = {args.provider: providers.get(args.provider)} if args.provider in providers else {}
        if not providers:
            console.print("[red]No providers available[/red]")
            return

        for pid, provider in providers.items():
            console.print(f"Fetching models from [cyan]{pid}[/cyan]...")
            try:
                models = provider.list_models()
                save_cached_models(pid, models)
                console.print(f"  [green]Found {len(models)} models[/green]")
            except Exception as e:
                console.print(f"  [red]Failed: {e}[/red]")

    elif args.models_command == "test":
        providers = router.get_available_providers()
        if args.provider:
            providers = {args.provider: providers.get(args.provider)} if args.provider in providers else {}
        if not providers:
            console.print("[red]No providers available[/red]")
            return

        for pid, provider in providers.items():
            console.print(f"Testing [cyan]{pid}[/cyan]...")
            health = provider.test_connection()
            if health.healthy:
                console.print(f"  [green]✓ {health.message} ({health.latency_ms}ms)[/green]")
            else:
                console.print(f"  [red]✗ {health.message}[/red]")

    else:
        console.print("[yellow]Usage: seeker_os models {list|search|fetch|test}[/yellow]")


def cmd_resume(args: argparse.Namespace) -> None:
    """Resume generation commands."""
    from seeker_os.config import Settings

    settings = Settings()

    if args.resume_command == "generate":
        from seeker_os.resume.generator import generate_resume
        console.print(f"Generating resume for job {args.job_id}...")
        try:
            result = generate_resume(settings, job_id=args.job_id, task=args.task)
            console.print(f"[green]✓ Resume generated (ID: {result['resume_id']})[/green]")
            console.print(f"  Provider: {result['provider']}/{result['model']}")
            console.print(f"  Tokens: {result['input_tokens']} in, {result['output_tokens']} out")
            console.print(f"  Validation: {'PASSED' if result['validation_passed'] else 'VIOLATIONS FOUND'}")
            if result["validation_violations"]:
                for v in result["validation_violations"]:
                    console.print(f"    [{v.get('severity', 'high')}] {v.get('violation', '')}")
            console.print(f"  File: {result['markdown_path']}")
        except Exception as e:
            console.print(f"[red]Failed: {e}[/red]")

    elif args.resume_command == "list":
        from seeker_os.resume.generator import list_resumes
        resumes = list_resumes(job_id=args.job if hasattr(args, "job") else None)

        from rich.table import Table
        table = Table(title="Generated Resumes")
        table.add_column("ID", style="cyan")
        table.add_column("Job ID")
        table.add_column("Model", style="green")
        table.add_column("Validation")
        table.add_column("Generated", style="dim")

        for r in resumes:
            table.add_row(
                str(r["id"]),
                str(r["job_id"]),
                r["model"],
                "✓" if r["validation_passed"] else "✗",
                r["generated_at"][:10] if r["generated_at"] else "",
            )
        console.print(table)

    elif args.resume_command == "show":
        from seeker_os.resume.generator import get_resume
        resume = get_resume(args.resume_id)
        if not resume:
            console.print(f"[red]Resume {args.resume_id} not found[/red]")
            return
        console.print(f"[bold]{resume['job_title']}[/bold] at [bold]{resume['job_company']}[/bold]")
        console.print(f"Generated: {resume['generated_at']}")
        console.print(f"Model: {resume['provider']}/{resume['model']}")
        console.print(f"Validation: {'PASSED' if resume['validation_passed'] else 'VIOLATIONS'}")
        console.print()
        console.print(resume["resume_text"])

    elif args.resume_command == "validate":
        from seeker_os.resume.validator import AccuracyValidator
        validator = AccuracyValidator(settings)
        try:
            result = validator.revalidate(args.resume_id)
            console.print(f"Validation: {'PASSED' if result.passed else 'VIOLATIONS FOUND'}")
            for v in result.violations:
                console.print(f"  [{v.severity}] {v.rule_id}: {v.violation}")
        except ValueError as e:
            console.print(f"[red]{e}[/red]")

    else:
        console.print("[yellow]Usage: seeker_os resume {generate|list|show|validate}[/yellow]")


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

    # models
    models_parser = subparsers.add_parser("models", help="LLM model management")
    models_sub = models_parser.add_subparsers(dest="models_command")

    models_list = models_sub.add_parser("list", help="List all models")
    models_list.add_argument("--provider", type=str, help="Filter by provider ID")

    models_search = models_sub.add_parser("search", help="Search models")
    models_search.add_argument("query", type=str, help="Search query")
    models_search.add_argument("--provider", type=str, help="Filter by provider")
    models_search.add_argument("--tag", type=str, help="Filter by tag (heavy/moderate/light)")

    models_fetch = models_sub.add_parser("fetch", help="Fetch models from provider APIs")
    models_fetch.add_argument("--provider", type=str, help="Fetch for specific provider")
    models_fetch.add_argument("--all", action="store_true", help="Fetch for all providers")

    models_test = models_sub.add_parser("test", help="Test provider connections")
    models_test.add_argument("--provider", type=str, help="Test specific provider")

    models_parser.set_defaults(func=cmd_models)

    # resume
    resume_parser = subparsers.add_parser("resume", help="Resume generation")
    resume_sub = resume_parser.add_subparsers(dest="resume_command")

    resume_gen = resume_sub.add_parser("generate", help="Generate resume for a job")
    resume_gen.add_argument("job_id", type=int, help="Job ID")
    resume_gen.add_argument("--task", type=str, default="resume_generation_standard",
                           help="LLM task (resume_generation_standard or resume_generation_high_value)")

    resume_list = resume_sub.add_parser("list", help="List generated resumes")
    resume_list.add_argument("--job", type=int, help="Filter by job ID")

    resume_show = resume_sub.add_parser("show", help="Show a resume")
    resume_show.add_argument("resume_id", type=int, help="Resume ID")

    resume_validate = resume_sub.add_parser("validate", help="Re-validate a resume")
    resume_validate.add_argument("resume_id", type=int, help="Resume ID")

    resume_parser.set_defaults(func=cmd_resume)

    args = parser.parse_args()
    if not args.command:
        parser.print_help()
        sys.exit(1)

    # Ensure DB is migrated
    run_migrations()

    args.func(args)


if __name__ == "__main__":
    main()
