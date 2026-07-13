#!/usr/bin/env python3
"""Export high-confidence cases from production scan history into a golden dataset.

Queries jobs + job_analyses + application_events for cases where the user's
apply/skip decision agrees with the LLM verdict, strips company-identifying
detail, and writes them to evals/golden_dataset.yml.

Usage:
    python3 scripts/export_golden_dataset.py [--db data/seeker.db] [--out evals/golden_dataset.yml] [--min-cases 20]
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Re-use the same decision derivation as calibration.py
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "backend"))
from seeker_os.scoring.calibration import derive_decisions  # noqa: E402


def _strip_company(jd_text: str, company: str) -> str:
    """Replace company-identifying detail with a generic placeholder."""
    if not company:
        return jd_text
    # Replace the company name (case-insensitive) with a placeholder
    result = jd_text
    for variant in {company, company.lower(), company.upper()}:
        result = result.replace(variant, "[COMPANY]")
    return result


def _extract_gaps(analysis_json: str | None) -> list[str]:
    """Extract named gap areas from the analysis JSON."""
    if not analysis_json:
        return []
    try:
        data = json.loads(analysis_json)
    except (json.JSONDecodeError, TypeError):
        return []
    return [g.get("area", "") for g in data.get("named_gaps", []) if g.get("area")]


def export_golden_dataset(
    db_path: str = "data/seeker.db",
    out_path: str = "evals/golden_dataset.yml",
    min_cases: int = 20,
) -> int:
    """Export high-confidence cases to the golden dataset.

    Returns the number of new cases added.
    """
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # 1. Derive user decisions from event log
    decisions = derive_decisions(conn)

    # 2. Find jobs with verdict + jd_full + candidate decision
    rows = conn.execute(
        """
        SELECT DISTINCT j.id, j.title, j.company, j.analysis_verdict,
               j.jd_full, j.location, j.comp_min, j.comp_max, j.apply_url,
               j.score, j.net_score
        FROM jobs j
        JOIN application_events ae ON ae.job_id = j.id
        WHERE j.analysis_verdict IS NOT NULL AND j.analysis_verdict != ''
          AND j.jd_full IS NOT NULL AND j.jd_full != ''
          AND ae.actor = 'candidate'
          AND ae.event_type IN ('applied', 'skipped', 'rejected')
        ORDER BY j.analysis_verdict, j.id
        """,
    ).fetchall()

    # 3. Get the latest analysis per job for gap data
    analyses: dict[int, str | None] = {}
    arows = conn.execute(
        "SELECT job_id, analysis_json FROM job_analyses ORDER BY analyzed_at DESC"
    ).fetchall()
    for r in arows:
        if r["job_id"] not in analyses:
            analyses[r["job_id"]] = r["analysis_json"]

    # 4. Filter to agreeing cases
    agree_cases = []
    for r in rows:
        jid = r["id"]
        dec = decisions.get(jid, {}).get("decision")
        if dec is None:
            continue
        v = r["analysis_verdict"]
        is_agree = (
            (v == "APPLY" and dec == "applied")
            or (v == "SKIP" and dec == "skipped")
            or (v == "CONDITIONAL" and dec == "applied")
            or (v == "MONITOR" and dec == "skipped")
        )
        if not is_agree:
            continue

        gaps = _extract_gaps(analyses.get(jid))
        agree_cases.append({
            "source_job_id": jid,
            "verdict": v,
            "decision": dec,
            "title": r["title"] or "",
            "company": r["company"] or "",
            "jd_text": _strip_company(r["jd_full"] or "", r["company"] or ""),
            "expected_verdict": v,
            "expected_gaps": gaps,
        })

    conn.close()

    if not agree_cases:
        print("No agreeing cases found — need scan history with user decisions.")
        return 0

    # 5. Load existing dataset (if any) to avoid duplicates
    out_file = Path(out_path)
    existing_ids: set[int] = set()
    existing_cases: list[dict] = []
    if out_file.exists():
        with open(out_file) as f:
            existing = yaml.safe_load(f) or {}
        for c in existing.get("cases", []):
            existing_cases.append(c)
            sid = c.get("source_job_id")
            if sid is not None:
                existing_ids.add(sid)

    # 6. Build new case entries (skip ones already in the dataset)
    now = datetime.now(UTC).isoformat()
    new_cases = []
    for c in agree_cases:
        if c["source_job_id"] in existing_ids:
            continue
        new_cases.append({
            "id": f"case-{c['source_job_id']}",
            "source_job_id": c["source_job_id"],
            "jd_text": c["jd_text"],
            "expected_verdict": c["expected_verdict"],
            "expected_gaps": c["expected_gaps"],
            "source": f"production_scan_{c['source_job_id']}",
            "added_at": now,
            "status": "active",
        })

    if not new_cases:
        print(f"No new cases to add ({len(existing_ids)} already in dataset).")
        return 0

    # 7. Merge and write
    all_cases = existing_cases + new_cases
    dataset = {
        "description": (
            "Golden dataset for promptfoo evals — JD analysis verdict accuracy "
            "and resume generation faithfulness. Seeded from production scan "
            "history where the user's apply/skip decision agrees with the LLM "
            "verdict. Cases are append-only; superseded cases are marked "
            "status: superseded and excluded from eval runs."
        ),
        "schema": {
            "id": "unique case identifier",
            "source_job_id": "original job ID in production DB (for traceability)",
            "jd_text": "job description text (company names stripped)",
            "expected_verdict": "APPLY | CONDITIONAL | MONITOR | SKIP",
            "expected_gaps": "list of gap area names from the original analysis",
            "source": "provenance label",
            "added_at": "ISO timestamp when the case was added",
            "status": "active | superseded",
        },
        "cases": all_cases,
    }

    out_file.parent.mkdir(parents=True, exist_ok=True)
    with open(out_file, "w") as f:
        yaml.dump(dataset, f, default_flow_style=False, allow_unicode=True, sort_keys=False)

    # Summary
    from collections import Counter
    verdict_counts = Counter(c["expected_verdict"] for c in new_cases)
    print(f"Added {len(new_cases)} new cases to {out_path}")
    print(f"  Verdicts: {dict(verdict_counts)}")
    print(f"  Total in dataset: {len(all_cases)}")

    if len(all_cases) < min_cases:
        print(f"  WARNING: dataset has {len(all_cases)} cases, below minimum of {min_cases}")

    return len(new_cases)


def main():
    parser = argparse.ArgumentParser(description="Export golden dataset from production scan history")
    parser.add_argument("--db", default="data/seeker.db", help="Path to seeker.db")
    parser.add_argument("--out", default="evals/golden_dataset.yml", help="Output path")
    parser.add_argument("--min-cases", type=int, default=20, help="Minimum cases warning threshold")
    args = parser.parse_args()

    count = export_golden_dataset(args.db, args.out, args.min_cases)
    sys.exit(0 if count > 0 else 1)


if __name__ == "__main__":
    main()
