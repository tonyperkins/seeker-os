"""hiring.cafe source adapter.

Fetches job cards from hiring.cafe's regular search by extracting
__NEXT_DATA__ JSON from the HTML response. See docs/SOURCE_ADAPTERS.md
and docs/HIRINGCAFE_FIELDS.md for details.
"""

from __future__ import annotations

import json
import re
import time
from urllib.parse import unquote

import httpx

from seeker_os.config import SourceConfig
from seeker_os.discovery.cache import DiskCache
from seeker_os.models import JobCard, SourcePage, SourceQuery


class HiringCafeAdapter:
    """hiring.cafe source adapter.

    Implements the SourceAdapter protocol. All source-specific logic is
    encapsulated here — the pipeline downstream never sees hiring.cafe-specific
    fields.
    """

    def __init__(self, config: SourceConfig, cache: DiskCache):
        self._id = config.id
        self._type = config.type
        self.base_url = config.base_url or "https://hiring.cafe"
        self.source_map = config.source_map
        self.request_delay = config.request_delay_seconds
        self.user_agent = config.user_agent
        self.max_retries = config.max_retries
        self.timeout = config.timeout_seconds
        self.cache = cache
        self._last_request_time: float = 0.0

    @property
    def id(self) -> str:
        return self._id

    @property
    def type(self) -> str:
        return self._type

    def _respect_delay(self) -> None:
        """Enforce human-like delay between requests."""
        elapsed = time.time() - self._last_request_time
        if elapsed < self.request_delay:
            time.sleep(self.request_delay - elapsed)

    def _fetch_html(self, url: str) -> str:
        """Fetch HTML with retry and delay. Returns HTML text."""
        cache_key = url
        cached = self.cache.get(cache_key)
        if cached is not None:
            return cached

        self._respect_delay()

        headers = {"User-Agent": self.user_agent}
        last_error: Exception | None = None

        for attempt in range(self.max_retries):
            try:
                resp = httpx.get(url, headers=headers, timeout=self.timeout, follow_redirects=True)
                if resp.status_code == 200:
                    self._last_request_time = time.time()
                    self.cache.set(cache_key, resp.text)
                    return resp.text
                elif resp.status_code in (429, 503):
                    # Exponential backoff
                    wait = (2 ** attempt) * self.request_delay
                    time.sleep(wait)
                    last_error = Exception(f"HTTP {resp.status_code} — rate limited")
                else:
                    last_error = Exception(f"HTTP {resp.status_code}")
            except Exception as e:
                last_error = e
                time.sleep(self.request_delay)

        raise RuntimeError(f"Failed to fetch {url} after {self.max_retries} attempts: {last_error}")

    def _extract_next_data(self, html: str) -> dict:
        """Extract __NEXT_DATA__ JSON from the HTML response."""
        match = re.search(
            r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
            html,
            re.DOTALL,
        )
        if not match:
            raise RuntimeError("__NEXT_DATA__ script tag not found in HTML response")
        return json.loads(match.group(1))

    def _parse_job_card(self, hit: dict, query_slug: str, detail_slug: str | None = None) -> JobCard | None:
        """Parse a single ssrHits[] entry into a JobCard.

        Returns None if the job should be skipped (pinned, malformed).
        """
        # Skip pinned jobs
        is_pinned = hit.get("is_hc_pinned", False) or hit.get("source") == "hiring_cafe_pin"
        if is_pinned:
            return None

        source_raw = hit.get("source", "")
        board_token = hit.get("board_token", "")
        raw_id = hit.get("id", "")

        # Decompose ID: source___board___jobid
        decoded_id = unquote(raw_id)
        parts = decoded_id.split("___")
        ats_job_id = parts[2] if len(parts) == 3 else raw_id

        # Map source code to canonical ATS name
        ats_source = self.source_map.get(source_raw, source_raw)
        if ats_source == "SKIP":
            return None

        # Extract v5 processed data
        v5 = hit.get("v5_processed_job_data", {})
        job_info = hit.get("job_information", {})
        enriched = hit.get("enriched_company_data", {})

        title = job_info.get("title", "") or v5.get("core_job_title", "")
        core_title = v5.get("core_job_title", title)

        # Company name may be missing — fall back through multiple sources
        company = v5.get("company_name") or enriched.get("name") or ""

        # Build detail URL from the slug extracted from HTML
        detail_url = f"{self.base_url}/job/{detail_slug}" if detail_slug else None

        # Normalize homepage URL — ensure it has a scheme
        homepage = enriched.get("homepage_uri") or ""
        if homepage and not homepage.startswith(("http://", "https://")):
            homepage = f"https://{homepage}"

        return JobCard(
            source_id=self._id,
            source_job_id=raw_id,
            ats_source=ats_source,
            ats_board_token=board_token or None,
            ats_job_id=ats_job_id,
            apply_url=hit.get("apply_url", ""),
            title=title,
            core_title=core_title,
            company=company,
            company_homepage=homepage or None,
            location=v5.get("formatted_workplace_location", ""),
            workplace_type=v5.get("workplace_type", ""),
            workplace_countries=v5.get("workplace_countries", []),
            seniority_level=v5.get("seniority_level"),
            commitment=v5.get("commitment", []),
            comp_min=v5.get("yearly_min_compensation"),
            comp_max=v5.get("yearly_max_compensation"),
            comp_currency=v5.get("listed_compensation_currency"),
            technical_tools=v5.get("technical_tools", []),
            requirements_summary=v5.get("requirements_summary", ""),
            date_posted=v5.get("estimated_publish_date", ""),
            role_type=v5.get("role_type"),
            is_pinned=is_pinned,
            discovered_query=query_slug,
            detail_url=detail_url,
        )

    def fetch_jobs(self, query: SourceQuery, page: int = 0) -> SourcePage:
        """Fetch one page from hiring.cafe.

        1. Check disk cache (key: {slug}:{page})
        2. GET {base_url}/jobs/{slug}?page={page}
        3. Extract __NEXT_DATA__ JSON
        4. Parse ssrHits[] → JobCard (using source_map for ATS normalization)
        5. Filter pinned jobs
        6. Cache response
        7. Return SourcePage
        """
        url = f"{self.base_url}/jobs/{query.slug}"
        if page > 0:
            url += f"?page={page}"
        html = self._fetch_html(url)
        data = self._extract_next_data(html)

        page_props = data.get("props", {}).get("pageProps", {})
        hits = page_props.get("ssrHits", [])
        total_count = page_props.get("ssrTotalCount", 0)
        is_last_page = page_props.get("ssrIsLastPage", True)

        # Extract /job/{slug} links from HTML and map them to hits by requisition_id
        # The slug format is {title}-{company}-{location}-{requisition_id}
        # We match using the requisition_id suffix which is unique per job
        detail_slugs: dict[str, str] = {}  # requisition_id → slug
        for slug in re.findall(r'href="/job/([^"]+)"', html):
            # The last segment after the final dash is the requisition_id
            parts = slug.rsplit("-", 1)
            if len(parts) == 2:
                detail_slugs[parts[1]] = slug

        jobs: list[JobCard] = []
        for hit in hits:
            req_id = hit.get("requisition_id", "")
            detail_slug = detail_slugs.get(req_id)
            card = self._parse_job_card(hit, query.slug, detail_slug=detail_slug)
            if card is not None:
                jobs.append(card)

        return SourcePage(
            jobs=jobs,
            total_count=total_count,
            is_last_page=is_last_page,
            source=self._id,
        )

    def test_connection(self) -> bool:
        """Verify hiring.cafe is reachable and __NEXT_DATA__ is present."""
        try:
            url = f"{self.base_url}/jobs/senior-sre-remote"
            html = self._fetch_html(url)
            self._extract_next_data(html)
            return True
        except Exception:
            return False
