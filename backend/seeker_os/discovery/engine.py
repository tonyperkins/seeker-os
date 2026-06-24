"""Discovery engine — iterates sources × queries, normalizes results to JobCard."""

from __future__ import annotations

from seeker_os.discovery.cache import DiskCache
from seeker_os.discovery.sources.base import SourceAdapter
from seeker_os.models import JobCard, SourceQuery


def fetch_all_queries(
    queries: list[SourceQuery],
    adapters: dict[str, SourceAdapter],
    cache: DiskCache,
) -> list[JobCard]:
    """Fetch all enabled queries across all sources, with delay between requests.

    For each query:
      - Look up adapter by query.source_id
      - Fetch pages 0 to query.max_pages-1
      - Respect adapter-specific request delay (from sources.yml)
      - Stop early if SourcePage.is_last_page is true
    Deduplicate across queries (same source_job_id appearing in multiple queries).
    Return combined list of unique JobCards.
    """
    all_jobs: list[JobCard] = []
    seen_ids: set[str] = set()

    for query in queries:
        if not query.enabled:
            continue

        adapter = adapters.get(query.source_id)
        if adapter is None:
            print(f"  WARNING: No adapter for source_id '{query.source_id}' — skipping query '{query.slug}'")
            continue

        for page in range(query.max_pages):
            print(f"  Query: {query.slug} (page {page})...", end=" ", flush=True)
            source_page = adapter.fetch_jobs(query, page=page)
            print(f"{len(source_page.jobs)} cards")

            for job in source_page.jobs:
                if job.source_job_id not in seen_ids:
                    seen_ids.add(job.source_job_id)
                    all_jobs.append(job)

            if source_page.is_last_page:
                break

    return all_jobs
