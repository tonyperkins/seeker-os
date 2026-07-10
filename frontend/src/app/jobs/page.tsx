"use client";

import { Suspense, useEffect, useState, useCallback, useRef } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, Loader2, Pin, Brain, Building2, FileText, CheckSquare, Square, ChevronDown, ChevronLeft, ChevronRight, CheckCircle2, XCircle, MinusCircle, Send, CircleDashed, Filter, FileSearch, X, RotateCcw, ArrowUpDown, ArrowUp, ArrowDown, UserX, RefreshCw, Users } from "lucide-react";
import {
  Card,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Separator } from "@/components/ui/separator";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type JobSortKey, type JobSummary } from "@/lib/api";
import { useDebouncedValue } from "@/lib/use-debounced-value";
import { AddJobDialog } from "@/components/add-job-dialog";
import { BulkAnnotateSkips } from "@/components/bulk-annotate-skips";
import { usePersistentState } from "@/lib/use-persistent-state";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { ErrorBanner } from "@/components/error-banner";

const STATUS_OPTIONS = [
  { value: "ready", label: "Ready" },
  { value: "reviewing", label: "Reviewing" },
  { value: "interested", label: "Interested" },
  { value: "applied", label: "Applied" },
];

const SOURCE_OPTIONS = [
  { value: "manual", label: "Manual" },
  { value: "hiring_cafe", label: "hiring.cafe" },
];

function statusIcon(status: string, isManual?: boolean) {
  const cls = "size-3.5 shrink-0";
  switch (status) {
    case "ready":
    case "interested":
    case "reviewing":
      return <CheckCircle2 className={`${cls} text-emerald-500`} />;
    case "rejected":
      return isManual
        ? <UserX className={`${cls} text-red-700 dark:text-red-400`} />
        : <XCircle className={`${cls} text-red-500`} />;
    case "skipped":
      return <MinusCircle className={`${cls} text-muted-foreground`} />;
    case "applied":
      return <Send className={`${cls} text-violet-500`} />;
    case "discovered":
      return <CircleDashed className={`${cls} text-amber-500`} />;
    case "filtered":
      return <Filter className={`${cls} text-orange-500`} />;
    case "jd_fetched":
      return <FileSearch className={`${cls} text-blue-500`} />;
    default:
      return <CircleDashed className={`${cls} text-muted-foreground/50`} />;
  }
}

function formatComp(min: number | null, max: number | null): string {
  if (min == null && max == null) return "—";
  const fmt = (n: number) => `$${(n / 1000).toFixed(0)}k`;
  if (min != null && max != null) return `${fmt(min)}–${fmt(max)}`;
  if (min != null) return `${fmt(min)}+`;
  return `≤${fmt(max as number)}`;
}

function statusRowClass(status: string): string {
  switch (status) {
    case "ready":
      return "bg-emerald-500/5 hover:bg-emerald-500/10";
    case "rejected":
      return "bg-red-500/5 hover:bg-red-500/10";
    case "reviewing":
    case "interested":
      return "bg-sky-500/5 hover:bg-sky-500/10";
    case "applied":
      return "bg-violet-500/5 hover:bg-violet-500/10";
    case "skipped":
      return "bg-muted/40 hover:bg-muted/60";
    case "discovered":
      return "bg-amber-500/5 hover:bg-amber-500/10";
    case "filtered":
      return "bg-orange-500/5 hover:bg-orange-500/10";
    case "jd_fetched":
      return "bg-blue-500/5 hover:bg-blue-500/10";
    default:
      return "";
  }
}

export default function JobsPage() {
  return (
    <Suspense fallback={
      <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
        <Loader2 className="animate-spin" />
        Loading jobs…
      </div>
    }>
      <JobsPageInner />
    </Suspense>
  );
}

function JobsPageInner() {
  const router = useRouter();
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
  const [selection, setSelection] = useState<{ scope: string; ids: Set<number> }>({ scope: "", ids: new Set() });
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkProgress, setBulkProgress] = useState<{ current: number; total: number; action: string } | null>(null);

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

  // Mark hydration complete after usePersistentState effects have run
  useEffect(() => {
    // This flag coordinates browser-only localStorage hydration.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHydrated(true);
  }, []);

  useEffect(() => {
    // Skip the first fetch — usePersistentState hasn't hydrated from localStorage yet.
    // After hydration, filters will have correct values and this effect re-fires.
    if (!hydrated) return;
    const controller = new AbortController();
    // Network synchronization intentionally owns the query result state.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    void fetchJobs(controller.signal);
    return () => controller.abort();
  }, [fetchJobs, hydrated]);

  // Reset to page 1 when filters change (but not when page itself changes)
  const filterKey = `${status}|${minScore}|${company}|${search}|${source}|${runId}|${verdict}|${hideRejected}|${hideSkipped}`;
  const prevFilterKey = useRef(filterKey);
  useEffect(() => {
    if (prevFilterKey.current !== filterKey) {
      prevFilterKey.current = filterKey;
      setPage(1);
    }
  }, [filterKey, setPage]);

  // Keep URL in sync (shallow) — skip until hydrated to avoid stripping
  // clear_filters before usePersistentState has stabilized
  useEffect(() => {
    if (!hydrated) return;
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (minScore) params.set("min_score", minScore);
    if (company) params.set("company", company);
    if (search) params.set("search", search);
    if (source) params.set("source", source);
    if (runId) params.set("run_id", runId);
    if (verdict) params.set("verdict", verdict);
    if (hideRejected) params.set("hide_rejected", "1");
    if (hideSkipped) params.set("hide_skipped", "1");
    params.set("sort_by", sortKey);
    params.set("order", sortDir);
    if (page > 1) params.set("page", String(page));
    const qs = params.toString();
    router.replace(qs ? `/jobs?${qs}` : "/jobs", { scroll: false });
  }, [status, minScore, company, search, source, runId, verdict, hideRejected, hideSkipped, sortKey, sortDir, page, router, hydrated]);

  const displayedJobs = jobs ?? [];
  const selectionScope = `${filterKey}|${page}|${sortKey}|${sortDir}`;
  const selectedIds = selection.scope === selectionScope ? selection.ids : new Set<number>();

  function toggleSort(key: JobSortKey) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function sortIcon(key: JobSortKey) {
    if (sortKey !== key) return <ArrowUpDown className="size-3 text-muted-foreground/50" />;
    return sortDir === "asc" ? <ArrowUp className="size-3 text-primary" /> : <ArrowDown className="size-3 text-primary" />;
  }

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

  const allSelected = displayedJobs.length > 0 && displayedJobs.every((j) => selectedIds.has(j.id));
  const someSelected = selectedIds.size > 0;

  function toggleJob(id: number) {
    setSelection((previous) => {
      const next = new Set(previous.scope === selectionScope ? previous.ids : []);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return { scope: selectionScope, ids: next };
    });
  }

  function toggleAll() {
    if (allSelected) {
      setSelection({ scope: selectionScope, ids: new Set() });
    } else {
      setSelection({ scope: selectionScope, ids: new Set(displayedJobs.map((j) => j.id)) });
    }
  }

  async function runBulkAction(
    action: string,
    fn: (id: number) => Promise<unknown>,
  ) {
    setBulkLoading(true);
    setBulkError(null);
    const ids = [...selectedIds];
    const errors: string[] = [];
    for (let i = 0; i < ids.length; i++) {
      setBulkProgress({ current: i + 1, total: ids.length, action });
      try {
        await fn(ids[i]);
      } catch (err) {
        errors.push(`Job ${ids[i]}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    setBulkLoading(false);
    setBulkProgress(null);
    setSelection({ scope: selectionScope, ids: new Set() });
    if (errors.length > 0) {
      setBulkError(`${action}: ${errors.length}/${ids.length} failed — ${errors.slice(0, 3).join("; ")}${errors.length > 3 ? "…" : ""}`);
    } else {
      setBulkError(null);
    }
    await fetchJobs();
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Jobs</h1>
        </div>
        <div className="flex items-center gap-2">
          <BulkAnnotateSkips />
          <AddJobDialog onCreated={() => void fetchJobs()} />
        </div>
      </div>

      {/* Filters */}
      <CollapsibleCard
        title={
          <div className="flex items-center gap-2">
            Filters
            {(status || source || minScore || runId || search || company || verdict || hideRejected || hideSkipped) && (
              <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
                {[status, source, minScore, runId, search, company, verdict, hideRejected ? "hr" : null, hideSkipped ? "hs" : null].filter(Boolean).length}
              </Badge>
            )}
          </div>
        }
        icon={Filter}
        defaultOpen={true}
        action={
          <Button
            variant="ghost"
            size="sm"
            onClick={resetFilters}
            title="Clear all filters"
            className="h-7 text-xs text-muted-foreground hover:text-foreground"
          >
            <RotateCcw className="size-3.5" />
            Reset
          </Button>
        }
      >
        <div className="flex flex-col gap-4">
          {/* Status + Source pills */}
          <div className="flex flex-wrap items-start gap-4 sm:gap-6">
            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-[48px] text-xs font-normal text-muted-foreground">Status</span>
              <button
                onClick={() => setStatus("")}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  status === ""
                    ? "border-foreground/20 bg-foreground/20 text-foreground"
                    : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                All
              </button>
              {STATUS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setStatus(opt.value)}
                  className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                    status === opt.value
                      ? "border-foreground/20 bg-foreground/20 text-foreground"
                      : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <Separator orientation="vertical" className="hidden h-6 self-center bg-border/50 sm:block" />

            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-[44px] text-xs font-normal text-muted-foreground">Source</span>
              <button
                onClick={() => setSource("")}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  source === ""
                    ? "border-foreground/20 bg-foreground/20 text-foreground"
                    : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                All
              </button>
              {SOURCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSource(opt.value)}
                  className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                    source === opt.value
                      ? "border-foreground/20 bg-foreground/20 text-foreground"
                      : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <Separator className="bg-border/50" />

          {/* Verdict pills + Hide toggles */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-[48px] text-xs font-normal text-muted-foreground">Verdict</span>
            <button
              onClick={() => setVerdict("")}
              className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                verdict === ""
                  ? "border-foreground/20 bg-foreground/20 text-foreground"
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
              }`}
            >
              All
            </button>
            {([
              { value: "APPLY", label: "Apply", activeClass: "border-border bg-emerald-600 text-white" },
              { value: "CONDITIONAL", label: "Conditional", activeClass: "border-border bg-amber-600 text-white" },
              { value: "MONITOR", label: "Monitor", activeClass: "border-border bg-sky-600 text-white" },
              { value: "SKIP", label: "Skip", activeClass: "border-border bg-red-600 text-white" },
            ] as const).map((opt) => (
              <button
                key={opt.value}
                onClick={() => setVerdict(opt.value)}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  verdict === opt.value
                    ? opt.activeClass
                    : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                {opt.label}
              </button>
            ))}
            <div className="ml-auto flex flex-wrap items-center gap-2">
              <span className="text-xs font-normal text-muted-foreground">Hide</span>
              <button
                onClick={() => setHideRejected(!hideRejected)}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  hideRejected
                    ? "border-border bg-red-600 text-white"
                    : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                Rejected
              </button>
              <button
                onClick={() => setHideSkipped(!hideSkipped)}
                className={`rounded-md border px-3 py-1 text-xs font-medium transition-all ${
                  hideSkipped
                  ? "border-foreground/20 bg-foreground/20 text-foreground"
                  : "border-border bg-transparent text-muted-foreground hover:border-foreground/30 hover:text-foreground"
                }`}
              >
                Skipped
              </button>
            </div>
          </div>

          <Separator className="bg-border/50" />
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-muted-foreground">Min score</label>
              <Input
                type="number"
                min={0}
                max={100}
                step="0.1"
                placeholder="0"
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
                className="w-24"
              />
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-muted-foreground">Run ID</label>
              <Input
                type="text"
                placeholder="e.g. 0627"
                value={runId}
                onChange={(e) => setRunId(e.target.value)}
                className="w-28"
              />
            </div>

            <div className="flex flex-1 flex-col gap-1.5">
              <label className="text-xs font-semibold text-muted-foreground">Search</label>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  type="text"
                  placeholder="Search title, company, location, reject reason…"
                  value={search}
                  onChange={(e) => setSearch(e.target.value)}
                  className="pl-8 pr-8"
                />
                {search && (
                  <button
                    onClick={() => setSearch("")}
                    className="absolute right-2 top-1/2 -translate-y-1/2 text-muted-foreground hover:text-foreground"
                  >
                    <X className="size-4" />
                  </button>
                )}
              </div>
            </div>

            <Button size="sm" onClick={() => void fetchJobs()} disabled={loading}>
              {loading ? <Loader2 className="animate-spin" /> : <Search className="size-4" />}
              Refresh
            </Button>
          </div>
        </div>
      </CollapsibleCard>

      {/* Bulk action toolbar */}
      {someSelected && (
        <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/30 p-2.5">
          <span className="text-sm font-medium">
            {selectedIds.size} selected on this page
          </span>
          {bulkError && (
            <span className="text-xs text-destructive">{bulkError}</span>
          )}
          <div className="flex-1" />
          {bulkLoading && bulkProgress && (
            <div className="flex items-center gap-2 text-sm text-muted-foreground">
              <Loader2 className="size-4 animate-spin" />
              <span>{bulkProgress.action}: {bulkProgress.current}/{bulkProgress.total}</span>
            </div>
          )}
          <DropdownMenu>
            <DropdownMenuTrigger
              render={
                <Button variant="outline" size="sm" disabled={bulkLoading}>
                  Set status <ChevronDown className="size-3.5" />
                </Button>
              }
            />
            <DropdownMenuContent align="end">
              {STATUS_OPTIONS.filter((o) => o.value).map((opt) => (
                <DropdownMenuItem
                  key={opt.value}
                  onClick={() => runBulkAction(`Set ${opt.label}`, (id) => api.jobs.update(id, { status: opt.value }))}
                >
                  {opt.label}
                </DropdownMenuItem>
              ))}
              <DropdownMenuSeparator />
              <DropdownMenuItem
                onClick={() => runBulkAction("Reject", (id) => api.jobs.update(id, { status: "rejected" }))}
              >
                Reject
              </DropdownMenuItem>
              <DropdownMenuItem
                onClick={() => runBulkAction("Skip", (id) => api.jobs.skip(id))}
              >
                Skip
              </DropdownMenuItem>
            </DropdownMenuContent>
          </DropdownMenu>
          <Button
            variant="outline"
            size="sm"
            disabled={bulkLoading}
            onClick={() => runBulkAction("AI Analysis", (id) => api.jobs.analysis.run(id))}
          >
            <Brain className="size-3.5" />
            Run Analysis
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={bulkLoading}
            onClick={() => runBulkAction("Company Research", (id) => api.jobs.companyResearch.run(id))}
          >
            <Building2 className="size-3.5" />
            Run Research
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={bulkLoading}
            title="Run AI Analysis + Company Research for each selected job"
            onClick={() => runBulkAction("Analysis + Research", async (id) => {
              await api.jobs.analysis.run(id);
              await api.jobs.companyResearch.run(id);
            })}
          >
            <Brain className="size-3.5" />
            <Building2 className="size-3.5 -ml-1" />
            Analysis + Research
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={bulkLoading}
            onClick={() => runBulkAction("Refilter & Rescore", (id) => api.jobs.refilterRescore({ job_ids: [id] }))}
          >
            <RefreshCw className="size-3.5" />
            Refilter & Rescore
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={bulkLoading}
            onClick={() => runBulkAction("Generate Resume", (id) => api.resumes.generate(id))}
          >
            <FileText className="size-3.5" />
            Gen Resume
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelection({ scope: selectionScope, ids: new Set() })}
          >
            Clear
          </Button>
        </div>
      )}

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {error ? (
            <div className="p-6">
              <ErrorBanner message={error} />
            </div>
          ) : loading && !jobs ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="animate-spin" />
              Loading jobs…
            </div>
          ) : displayedJobs.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No jobs match these filters.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10 shrink-0">
                      <button onClick={toggleAll} className="flex items-center" aria-label="Select all jobs on this page">
                        {allSelected ? (
                          <CheckSquare className="size-4 text-primary" />
                        ) : (
                          <Square className="size-4 text-muted-foreground" />
                        )}
                      </button>
                    </TableHead>
                    <TableHead className="w-14 shrink-0">
                      <button onClick={() => toggleSort("score")} className="flex items-center gap-1 hover:text-foreground">
                        Score {sortIcon("score")}
                      </button>
                    </TableHead>
                    <TableHead className="w-28 shrink-0">
                      <button onClick={() => toggleSort("status")} className="flex items-center gap-1 hover:text-foreground">
                        Status {sortIcon("status")}
                      </button>
                    </TableHead>
                    <TableHead className="w-20 shrink-0">
                      <button onClick={() => toggleSort("run_id")} className="flex items-center gap-1 hover:text-foreground">
                        Run {sortIcon("run_id")}
                      </button>
                    </TableHead>
                    <TableHead className="min-w-[160px] max-w-[260px]">
                      <button onClick={() => toggleSort("title")} className="flex items-center gap-1 hover:text-foreground">
                        Title {sortIcon("title")}
                      </button>
                    </TableHead>
                    <TableHead className="min-w-[100px] max-w-[180px]">
                      <button onClick={() => toggleSort("company")} className="flex items-center gap-1 hover:text-foreground">
                        Company {sortIcon("company")}
                      </button>
                    </TableHead>
                    <TableHead className="w-28 shrink-0">
                      <button onClick={() => toggleSort("comp")} className="flex items-center gap-1 hover:text-foreground">
                        Comp {sortIcon("comp")}
                      </button>
                    </TableHead>
                    <TableHead className="min-w-[80px] max-w-[140px]">
                      <button onClick={() => toggleSort("location")} className="flex items-center gap-1 hover:text-foreground">
                        Location {sortIcon("location")}
                      </button>
                    </TableHead>
                    <TableHead className="w-24 shrink-0">
                      <button onClick={() => toggleSort("ats")} className="flex items-center gap-1 hover:text-foreground">
                        ATS {sortIcon("ats")}
                      </button>
                    </TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {displayedJobs.map((job) => (
                    <TableRow
                      key={job.id}
                      className={`cursor-pointer ${statusRowClass(job.status)}`}
                      onClick={() => router.push(`/jobs/${job.id}`)}
                    >
                      <TableCell className="w-10 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <button
                          onClick={() => toggleJob(job.id)}
                          className="flex items-center"
                          aria-label={`Select ${job.title} at ${job.company}`}
                        >
                          {selectedIds.has(job.id) ? (
                            <CheckSquare className="size-4 text-primary" />
                          ) : (
                            <Square className="size-4 text-muted-foreground" />
                          )}
                        </button>
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono font-medium">
                        <div className="flex flex-col items-center">
                          <span>{job.score != null ? job.score : "—"}</span>
                          {job.net_score != null && job.net_score !== job.score && (
                            <span className="text-xs text-muted-foreground" title="Net score (base + research, capped by AI verdict)">
                              → {job.net_score.toFixed(1)}
                            </span>
                          )}
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap">
                        <div className="flex items-center gap-1" title={job.reject_reason ? (job.reject_details ? `Manually rejected: ${job.reject_reason}` : job.reject_reason) : job.status}>
                          {statusIcon(job.status, !!job.reject_details)}
                          <span title={job.has_analysis ? `Analysis: ${job.analysis_verdict ?? "done"}` : "No analysis"}>
                            <Brain className={`size-3.5 ${
                              !job.has_analysis
                                ? "text-muted-foreground/30"
                                : job.analysis_verdict === "APPLY"
                                  ? "text-emerald-500"
                                  : job.analysis_verdict === "CONDITIONAL"
                                    ? "text-amber-500"
                                    : job.analysis_verdict === "MONITOR"
                                      ? "text-sky-500"
                                      : job.analysis_verdict === "SKIP"
                                        ? "text-red-500"
                                        : "text-primary"
                            }`} />
                          </span>
                          <span title={job.has_research ? "Research done" : "No research"}>
                            <Building2 className={`size-3.5 ${job.has_research ? "text-primary" : "text-muted-foreground/30"}`} />
                          </span>
                          <span title={job.has_resume ? "Resume generated" : "No resume"}>
                            <FileText className={`size-3.5 ${job.has_resume ? "text-primary" : "text-muted-foreground/30"}`} />
                          </span>
                          <span title={job.has_recruiter ? `Recruiter: ${job.recruiter_source ?? "contact"}` : "No recruiter"}>
                            <Users className={`size-3.5 ${job.has_recruiter ? "text-primary" : "text-muted-foreground/30"}`} />
                          </span>
                        </div>
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                        {job.run_id ?? "—"}
                      </TableCell>
                      <TableCell className="max-w-[260px]">
                        <div className="flex items-center gap-1.5">
                          {job.is_pinned && <Pin className="size-3.5 shrink-0 text-amber-500" />}
                          <span className="truncate font-medium">{job.title}</span>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-muted-foreground">{job.company}</TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {formatComp(job.comp_min, job.comp_max)}
                      </TableCell>
                      <TableCell className="max-w-[140px] truncate text-muted-foreground">
                        {job.location || "—"}
                        {job.workplace_type && job.workplace_type !== "unknown" && (
                          <span className="ml-1 text-xs">· {job.workplace_type}</span>
                        )}
                      </TableCell>
                      <TableCell className="whitespace-nowrap text-muted-foreground">
                        {job.ats_source ?? "—"}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      {displayedJobs.length > 0 && (
        <div className="flex items-center justify-between gap-4">
          <p className="text-xs text-muted-foreground">
            Showing {(page - 1) * PAGE_SIZE + 1}–{(page - 1) * PAGE_SIZE + displayedJobs.length} of {total} job{total !== 1 ? "s" : ""}.
          </p>
          {total > PAGE_SIZE && (
            <div className="flex items-center gap-2">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1 || loading}
                onClick={() => setPage(page - 1)}
              >
                <ChevronLeft className="size-4" />
                Prev
              </Button>
              <span className="text-xs text-muted-foreground">
                Page {page} of {Math.ceil(total / PAGE_SIZE)}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= Math.ceil(total / PAGE_SIZE) || loading}
                onClick={() => setPage(page + 1)}
              >
                Next
                <ChevronRight className="size-4" />
              </Button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
