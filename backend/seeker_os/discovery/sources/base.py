"""Source adapter interface — pluggable job discovery.

hiring.cafe is one adapter. LinkedIn, Indeed, direct ATS scans, or any other
source can be added without touching the pipeline.
See docs/SOURCE_ADAPTERS.md for full design.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from seeker_os.models import SourcePage, SourceQuery


@runtime_checkable
class SourceAdapter(Protocol):
    """Abstract job source adapter. Each source implements this interface."""

    @property
    def id(self) -> str:
        """Adapter identifier (e.g. 'hiring_cafe')."""
        ...

    @property
    def type(self) -> str:
        """Adapter type (e.g. 'hiring_cafe', 'linkedin', 'ats_direct')."""
        ...

    def fetch_jobs(self, query: SourceQuery, page: int = 0) -> SourcePage:
        """Fetch one page of results for a query.

        Returns SourcePage with:
        - jobs: list[JobCard] (normalized to generic representation)
        - total_count: int (total results for this query)
        - is_last_page: bool
        """
        ...

    def test_connection(self) -> bool:
        """Test that the source is reachable and configured correctly."""
        ...
