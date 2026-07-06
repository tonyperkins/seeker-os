"""Cross-reference with the job-search repo.

Read-only access. Always git pull --rebase first.
Scans applied/, rejected/, closed/, opportunities/, found/ for prior interactions.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from rapidfuzz import fuzz

from seeker_os.dedup.normalize import normalize_company, normalize_title
from seeker_os.models import CrossRefResult


def _validate_git_repo(path: Path) -> bool:
    """Check that a path is a git repository (has a .git entry)."""
    git_dir = path / ".git"
    return git_dir.exists()


def sync_repo(repo_path: str) -> bool:
    """Git pull --rebase the job-search repo. Returns True on success."""
    path = Path(repo_path).expanduser()
    if not path.exists():
        print(f"  WARNING: Cross-reference repo not found at {path}")
        return False

    if not _validate_git_repo(path):
        print(f"  WARNING: Cross-reference path is not a git repository: {path}")
        return False

    try:
        subprocess.run(
            ["git", "pull", "--rebase"],
            cwd=str(path),
            capture_output=True,
            text=True,
            timeout=30,
            check=True,
        )
        return True
    except subprocess.CalledProcessError as e:
        print(f"  WARNING: git pull --rebase failed: {e.stderr}")
        return False
    except subprocess.TimeoutExpired:
        print("  WARNING: git pull --rebase timed out")
        return False
    except Exception as e:
        print(f"  WARNING: git pull --rebase error: {e}")
        return False


def _parse_status_md(content: str) -> dict[str, str]:
    """Parse a status.md file for company, title, date, score."""
    info: dict[str, str] = {}
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("Company:"):
            info["company"] = line.split(":", 1)[1].strip()
        elif line.startswith("Title:") or line.startswith("Role:"):
            info["title"] = line.split(":", 1)[1].strip()
        elif line.startswith("Date:"):
            info["date"] = line.split(":", 1)[1].strip()
        elif line.startswith("Score:"):
            score_str = line.split(":", 1)[1].strip()
            try:
                info["score"] = float(score_str)
            except ValueError:
                pass
    return info


def _parse_filename(filename: str) -> dict[str, str]:
    """Parse a filename for company and title (fallback when status.md is missing)."""
    # Filenames are often: "CompanyName-RoleName-score.md" or "CompanyName-RoleName.md"
    name = filename.replace(".md", "").replace("_", " ").replace("-", " ")
    return {"raw": name}


def _scan_directory(
    repo_path: Path,
    subdir: str,
    status_label: str,
) -> list[dict]:
    """Scan a directory for prior job interactions.

    Returns list of dicts with: company, title, status, date, score, raw_name.
    """
    results: list[dict] = []
    dir_path = repo_path / subdir
    if not dir_path.exists():
        return results

    # Handle subdirectory structure (applied/CompanyName/)
    for entry in dir_path.iterdir():
        if entry.name.startswith("."):
            continue

        if entry.is_dir():
            # Subdirectory with status.md
            status_file = entry / "status.md"
            if status_file.exists():
                info = _parse_status_md(status_file.read_text())
                results.append({
                    "company": info.get("company", entry.name.replace("-", " ")),
                    "title": info.get("title", ""),
                    "status": status_label,
                    "date": info.get("date", ""),
                    "score": info.get("score"),
                    "raw_name": entry.name,
                })
            else:
                # Try to find any .md file in the subdir
                md_files = list(entry.glob("*.md"))
                if md_files:
                    content = md_files[0].read_text()
                    info = _parse_status_md(content)
                    results.append({
                        "company": info.get("company", entry.name.replace("-", " ")),
                        "title": info.get("title", ""),
                        "status": status_label,
                        "date": info.get("date", ""),
                        "score": info.get("score"),
                        "raw_name": entry.name,
                    })
        elif entry.is_file() and entry.suffix == ".md":
            # Flat .md file
            content = entry.read_text()
            info = _parse_status_md(content)
            if not info.get("company"):
                # Fallback: parse filename
                fn_info = _parse_filename(entry.name)
                info["company"] = fn_info.get("raw", entry.name)
            results.append({
                "company": info.get("company", ""),
                "title": info.get("title", ""),
                "status": status_label,
                "date": info.get("date", ""),
                "score": info.get("score"),
                "raw_name": entry.name,
            })

    return results


def check_cross_reference(
    title: str,
    company: str,
    repo_path: str,
    title_threshold: int = 80,
    company_threshold: int = 80,
) -> CrossRefResult:
    """Check if a job matches anything in the job-search repo.

    Scans applied/, rejected/, closed/, opportunities/, found/.
    Matching: normalized company + title fuzzy match (rapidfuzz).

    Returns CrossRefResult.
    """
    path = Path(repo_path).expanduser()
    if not path.exists():
        return CrossRefResult(matched=False, match_confidence="")

    if not _validate_git_repo(path):
        return CrossRefResult(matched=False, match_confidence="")

    # Scan all directories
    all_prior: list[dict] = []
    for subdir, label in [
        ("applied", "applied"),
        ("rejected", "rejected"),
        ("closed", "closed"),
        ("opportunities", "opportunities"),
        ("found", "found"),
    ]:
        all_prior.extend(_scan_directory(path, subdir, label))

    if not all_prior:
        return CrossRefResult(matched=False, match_confidence="")

    new_title_norm = normalize_title(title)
    new_company_norm = normalize_company(company)

    best_match: dict | None = None
    best_score: float = 0.0

    for prior in all_prior:
        prior_title_norm = normalize_title(prior.get("title", "") or prior.get("raw_name", ""))
        prior_company_norm = normalize_company(prior.get("company", ""))

        title_score = fuzz.ratio(new_title_norm, prior_title_norm) if prior_title_norm else 0
        company_score = fuzz.ratio(new_company_norm, prior_company_norm) if prior_company_norm else 0

        # Combined score (weighted: company matters more for identity)
        combined = (company_score * 0.6 + title_score * 0.4)

        if company_score > company_threshold and combined > best_score:
            best_match = prior
            best_score = combined

    if best_match:
        confidence = "high" if best_score > 90 else "fuzzy"
        return CrossRefResult(
            matched=True,
            prior_status=best_match.get("status"),
            prior_date=best_match.get("date"),
            prior_score=best_match.get("score"),
            match_confidence=confidence,
        )

    return CrossRefResult(matched=False, match_confidence="")
