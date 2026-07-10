"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { api, type JobSortKey, type JobSummary } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { usePersistentState } from "@/lib/use-persistent-state";
import { useSearchParams } from "next/navigation";

export interface JobsQueryState {
  status: string;
  minScore: string;
  company: string;
  search: string;
  source: string;
  runId: string;
  verdict: string;
  hideRejected: boolean;
  hideSkipped: boolean;
  sortKey: JobSortKey;
  sortDir: "asc" | "desc";
  page: number;
}

export interface JobsQueryResult {
  state: JobsQueryState;
  setters: {
    setStatus: (v: string) => void;
    setMinScore: (v: string) => void;
    setCompany: (v: string) => void;
    setSearch: (v: string) => void;
    setSource: (v: string) => void;
    setRunId: (v: string) => void;
    setVerdict: (v: string) => void;
    setHideRejected: (v: boolean) => void;
    setHideSkipped: (v: boolean) => void;
    setSortKey: (v: JobSortKey) => void;
    setSortDir: (v: "asc" | "desc") => void;
    setPage: (v: number) => void;
  };
  jobs: JobSummary[] | null;
  total: number;
  loading: boolean;
  error: string | null;
  hydrated: boolean;
  filterKey: string;
  refetch: () => void;
  resetFilters: () => void;
}

export function useJobsQuery(): JobsQueryResult {
  const searchParams = useSearchParams();
  const clearFilters = searchParams.get("clear_filters") === "1";

  const [status, setStatus] = usePersistentState<string>("jobs:filter:status", searchParams.get("status") ?? "", !clearFilters && !searchParams.get("status"));
  const [minScore, setMinScore] = usePersistentState<string>("jobs:filter:minScore", searchParams.get("min_score") ?? "", !clearFilters && !searchParams.get("min_score"));
  const [company, setCompany] = usePersistentState<string>("jobs:filter:company", searchParams.get("company") ?? "", !clearFilters && !searchParams.get("company"));
  const [search, setSearch] = usePersistentState<string>("jobs:filter:search", searchParams.get("search") ?? "", !clearFilters && !searchParams.get("search"));
  const [source, setSource] = usePersistentState<string>("jobs:filter:source", searchParams.get("source") ?? "", !clearFilters && !searchParams.get("source"));
  const [runId, setRunId] = usePersistentState<string>("jobs:filter:runId", searchParams.get("run_id") ?? "", !clearFilters && !searchParams.get("run_id"));
  const [verdict, setVerdict] = usePersistentState<string>("jobs:filter:verdict", searchParams.get("verdict") ?? "", !clearFilters && !searchParams.get("verdict"));
  const [hideRejected, setHideRejected] = usePersistentState<boolean>("jobs:filter:hideRejected", searchParams.get("hide_rejected") === "1", !clearFilters && !searchParams.has("hide_rejected"));
  const [hideSkipped, setHideSkipped] = usePersistentState<boolean>("jobs:filter:hideSkipped", searchParams.get("hide_skipped") === "1", !clearFilters && !searchParams.has("hide_skipped"));
  const [sortKey, setSortKey] = usePersistentState<JobSortKey>("jobs:sort:key", (searchParams.get("sort_by") as JobSortKey | null) ?? "score", !clearFilters && !searchParams.has("sort_by"));
  const [sortDir, setSortDir] = usePersistentState<"asc" | "desc">("jobs:sort:dir", searchParams.get("order") === "asc" ? "asc" : "desc", !clearFilters && !searchParams.has("order"));
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [total, setTotal] = useState(0);
  const urlPage = Number.parseInt(searchParams.get("page") ?? "1", 10);
  const [page, setPage] = usePersistentState<number>("jobs:page", Number.isFinite(urlPage) && urlPage > 0 ? urlPage : 1, !clearFilters && !searchParams.has("page"));
  const PAGE_SIZE = 50;
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [hydrated, setHydrated] = useState(false);

  const debouncedSearch = useDebouncedValue(search, 300);
  const debouncedCompany = useDebouncedValue(company, 300);
  const debouncedRunId = useDebouncedValue(runId, 300);

  const fetchJobs = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError(null);
    try {
      const params: { status?: string; min_score?: number; company?: string; search?: string; source?: string; run_id?: string; verdict?: string; exclude_status?: string; sort_by: JobSortKey; order: "asc" | "desc"; limit?: number; offset?: number } = {
        limit: PAGE_SIZE,
        offset: (page - 1) * PAGE_SIZE,
        sort_by: sortKey,
        order: sortDir,
      };
      if (status) params.status = status;
      const ms = parseFloat(minScore);
      if (!isNaN(ms)) params.min_score = ms;
      if (debouncedCompany.trim()) params.company = debouncedCompany.trim();
      if (debouncedSearch.trim()) params.search = debouncedSearch.trim();
      if (source) params.source = source;
      if (debouncedRunId.trim()) params.run_id = debouncedRunId.trim();
      if (verdict) params.verdict = verdict;
      const excluded: string[] = [];
      if (hideRejected) excluded.push("rejected");
      if (hideSkipped) excluded.push("skipped");
      if (excluded.length > 0) params.exclude_status = excluded.join(",");
      const data = await api.jobs.list(params, { signal });
      if (signal?.aborted) return;
      setJobs(data.jobs);
      setTotal(data.total);
    } catch (err) {
      if (signal?.aborted || (err instanceof DOMException && err.name === "AbortError")) return;
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [status, minScore, debouncedCompany, debouncedSearch, source, debouncedRunId, verdict, hideRejected, hideSkipped, page, sortKey, sortDir]);

  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHydrated(true);
  }, []);

  useEffect(() => {
    if (!hydrated) return;
    const controller = new AbortController();
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchJobs(controller.signal);
    return () => controller.abort();
  }, [fetchJobs, hydrated]);

  const filterKey = `${status}|${minScore}|${company}|${search}|${source}|${runId}|${verdict}|${hideRejected}|${hideSkipped}`;
  const prevFilterKey = useRef(filterKey);
  useEffect(() => {
    if (prevFilterKey.current !== filterKey) {
      prevFilterKey.current = filterKey;
      setPage(1);
    }
  }, [filterKey, setPage]);

  function resetFilters() {
    setStatus("");
    setMinScore("");
    setCompany("");
    setSearch("");
    setSource("");
    setRunId("");
    setVerdict("");
    setHideRejected(false);
    setHideSkipped(false);
    setPage(1);
  }

  return {
    state: { status, minScore, company, search, source, runId, verdict, hideRejected, hideSkipped, sortKey, sortDir, page },
    setters: { setStatus, setMinScore, setCompany, setSearch, setSource, setRunId, setVerdict, setHideRejected, setHideSkipped, setSortKey, setSortDir, setPage },
    jobs,
    total,
    loading,
    error,
    hydrated,
    filterKey,
    refetch: () => void fetchJobs(),
    resetFilters,
  };
}
