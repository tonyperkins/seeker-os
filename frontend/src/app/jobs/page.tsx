"use client";

import { Suspense, useEffect, useState, useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, Loader2, Pin, Brain, Building2, FileText, CheckSquare, Square, ChevronDown, CheckCircle2, XCircle, MinusCircle, Send, CircleDashed, Filter, FileSearch, X, RotateCcw, ArrowUpDown, ArrowUp, ArrowDown, UserX } from "lucide-react";
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
import { api, type JobSummary } from "@/lib/api";
import { AddJobDialog } from "@/components/add-job-dialog";
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
  { value: "rejected", label: "Rejected" },
  { value: "reviewing", label: "Reviewing" },
  { value: "interested", label: "Interested" },
  { value: "applied", label: "Applied" },
  { value: "skipped", label: "Skipped" },
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

  const [status, setStatus] = usePersistentState<string>("jobs:filter:status", searchParams.get("status") ?? "", !searchParams.get("status"));
  const [minScore, setMinScore] = usePersistentState<string>("jobs:filter:minScore", searchParams.get("min_score") ?? "", !searchParams.get("min_score"));
  const [company, setCompany] = usePersistentState<string>("jobs:filter:company", searchParams.get("company") ?? "", !searchParams.get("company"));
  const [search, setSearch] = usePersistentState<string>("jobs:filter:search", searchParams.get("search") ?? "", !searchParams.get("search"));
  const [source, setSource] = usePersistentState<string>("jobs:filter:source", searchParams.get("source") ?? "", !searchParams.get("source"));
  const [runId, setRunId] = usePersistentState<string>("jobs:filter:runId", searchParams.get("run_id") ?? "", !searchParams.get("run_id"));
  const [verdict, setVerdict] = usePersistentState<string>("jobs:filter:verdict", searchParams.get("verdict") ?? "", !searchParams.get("verdict"));
  const [sortKey, setSortKey] = usePersistentState<string>("jobs:sort:key", "score");
  const [sortDir, setSortDir] = usePersistentState<"asc" | "desc">("jobs:sort:dir", "desc");
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [selectedIds, setSelectedIds] = useState<Set<number>>(new Set());
  const [bulkLoading, setBulkLoading] = useState(false);
  const [bulkError, setBulkError] = useState<string | null>(null);
  const [bulkProgress, setBulkProgress] = useState<{ current: number; total: number; action: string } | null>(null);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { status?: string; min_score?: number; company?: string; search?: string; source?: string; run_id?: string; verdict?: string; limit?: number } = {
        limit: 200,
      };
      if (status) params.status = status;
      const ms = parseFloat(minScore);
      if (!isNaN(ms)) params.min_score = ms;
      if (company.trim()) params.company = company.trim();
      if (search.trim()) params.search = search.trim();
      if (source) params.source = source;
      if (runId.trim()) params.run_id = runId.trim();
      if (verdict) params.verdict = verdict;
      const data = await api.jobs.list(params);
      setJobs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, [status, minScore, company, search, source, runId, verdict]);

  useEffect(() => {
    // Fetch on mount and when filters change — legitimate data-fetching effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchJobs();
  }, [fetchJobs]);

  // Keep URL in sync (shallow)
  useEffect(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (minScore) params.set("min_score", minScore);
    if (company) params.set("company", company);
    if (search) params.set("search", search);
    if (source) params.set("source", source);
    if (runId) params.set("run_id", runId);
    if (verdict) params.set("verdict", verdict);
    const qs = params.toString();
    router.replace(qs ? `/jobs?${qs}` : "/jobs", { scroll: false });
  }, [status, minScore, company, search, source, runId, verdict, router]);

  const sortedJobs = useMemo(() => {
    if (!jobs) return [];
    const sorted = [...jobs];
    sorted.sort((a, b) => {
      let cmp = 0;
      switch (sortKey) {
        case "score":
          cmp = (a.score ?? -1) - (b.score ?? -1);
          break;
        case "status":
          cmp = a.status.localeCompare(b.status);
          break;
        case "run_id":
          cmp = (a.run_id ?? "").localeCompare(b.run_id ?? "", undefined, { numeric: true });
          break;
        case "title":
          cmp = a.title.localeCompare(b.title);
          break;
        case "company":
          cmp = a.company.localeCompare(b.company);
          break;
        case "comp":
          cmp = (a.comp_min ?? 0) - (b.comp_min ?? 0);
          break;
        case "location":
          cmp = (a.location || "").localeCompare(b.location || "");
          break;
        case "ats":
          cmp = (a.ats_source ?? "").localeCompare(b.ats_source ?? "");
          break;
        default:
          cmp = 0;
      }
      return sortDir === "asc" ? cmp : -cmp;
    });
    return sorted;
  }, [jobs, sortKey, sortDir]);

  function toggleSort(key: string) {
    if (sortKey === key) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortKey(key);
      setSortDir("desc");
    }
  }

  function sortIcon(key: string) {
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
  }

  const allSelected = sortedJobs.length > 0 && sortedJobs.every((j) => selectedIds.has(j.id));
  const someSelected = selectedIds.size > 0;

  function toggleJob(id: number) {
    setSelectedIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleAll() {
    if (allSelected) {
      setSelectedIds(new Set());
    } else {
      setSelectedIds(new Set(sortedJobs.map((j) => j.id)));
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
          <p className="text-sm text-muted-foreground">
            All discovered jobs with filtering and search.
          </p>
        </div>
        <AddJobDialog onCreated={fetchJobs} />
      </div>

      {/* Filters */}
      <CollapsibleCard
        title={
          <div className="flex items-center gap-2">
            Filters
            {(status || source || minScore || runId || search || company || verdict) && (
              <Badge variant="secondary" className="h-4 px-1.5 text-[10px]">
                {[status, source, minScore, runId, search, company, verdict].filter(Boolean).length}
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
              <span className="min-w-[48px] text-xs font-semibold text-muted-foreground">Status</span>
              <button
                onClick={() => setStatus("")}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                  status === ""
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "border border-transparent bg-secondary/60 text-secondary-foreground hover:bg-secondary"
                }`}
              >
                All
              </button>
              {STATUS_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setStatus(opt.value)}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                    status === opt.value
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "border border-transparent bg-secondary/60 text-secondary-foreground hover:bg-secondary"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>

            <Separator orientation="vertical" className="hidden h-6 self-center bg-border/50 sm:block" />

            <div className="flex flex-wrap items-center gap-2">
              <span className="min-w-[44px] text-xs font-semibold text-muted-foreground">Source</span>
              <button
                onClick={() => setSource("")}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                  source === ""
                    ? "bg-primary text-primary-foreground shadow-sm"
                    : "border border-transparent bg-secondary/60 text-secondary-foreground hover:bg-secondary"
                }`}
              >
                All
              </button>
              {SOURCE_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  onClick={() => setSource(opt.value)}
                  className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                    source === opt.value
                      ? "bg-primary text-primary-foreground shadow-sm"
                      : "border border-transparent bg-secondary/60 text-secondary-foreground hover:bg-secondary"
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>

          <Separator className="bg-border/50" />

          {/* Verdict pills */}
          <div className="flex flex-wrap items-center gap-2">
            <span className="min-w-[48px] text-xs font-semibold text-muted-foreground">Verdict</span>
            <button
              onClick={() => setVerdict("")}
              className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                verdict === ""
                  ? "bg-primary text-primary-foreground shadow-sm"
                  : "border border-transparent bg-secondary/60 text-secondary-foreground hover:bg-secondary"
              }`}
            >
              All
            </button>
            {([
              { value: "APPLY", label: "Apply", activeClass: "bg-emerald-500 text-white shadow-sm" },
              { value: "CONDITIONAL", label: "Conditional", activeClass: "bg-amber-500 text-white shadow-sm" },
              { value: "MONITOR", label: "Monitor", activeClass: "bg-sky-500 text-white shadow-sm" },
              { value: "SKIP", label: "Skip", activeClass: "bg-red-500 text-white shadow-sm" },
            ] as const).map((opt) => (
              <button
                key={opt.value}
                onClick={() => setVerdict(opt.value)}
                className={`rounded-full px-3 py-1 text-xs font-medium transition-all ${
                  verdict === opt.value
                    ? opt.activeClass
                    : "border border-transparent bg-secondary/60 text-secondary-foreground hover:bg-secondary"
                }`}
              >
                {opt.label}
              </button>
            ))}
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

            <Button size="sm" onClick={fetchJobs} disabled={loading}>
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
            {selectedIds.size} selected
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
            onClick={() => runBulkAction("Generate Resume", (id) => api.resumes.generate(id))}
          >
            <FileText className="size-3.5" />
            Gen Resume
          </Button>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => setSelectedIds(new Set())}
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
          ) : loading ? (
            <div className="flex items-center justify-center gap-2 py-12 text-sm text-muted-foreground">
              <Loader2 className="animate-spin" />
              Loading jobs…
            </div>
          ) : sortedJobs.length === 0 ? (
            <p className="py-12 text-center text-sm text-muted-foreground">
              No jobs match these filters.
            </p>
          ) : (
            <div className="overflow-x-auto">
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-10 shrink-0">
                      <button onClick={toggleAll} className="flex items-center">
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
                  {sortedJobs.map((job) => (
                    <TableRow
                      key={job.id}
                      className={`cursor-pointer ${statusRowClass(job.status)}`}
                      onClick={() => router.push(`/jobs/${job.id}`)}
                    >
                      <TableCell className="w-10 shrink-0" onClick={(e) => e.stopPropagation()}>
                        <button onClick={() => toggleJob(job.id)} className="flex items-center">
                          {selectedIds.has(job.id) ? (
                            <CheckSquare className="size-4 text-primary" />
                          ) : (
                            <Square className="size-4 text-muted-foreground" />
                          )}
                        </button>
                      </TableCell>
                      <TableCell className="whitespace-nowrap font-mono font-medium">
                        {job.score != null ? job.score : "—"}
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

      {sortedJobs.length > 0 && (
        <p className="text-xs text-muted-foreground">
          Showing {sortedJobs.length} job{sortedJobs.length !== 1 ? "s" : ""}.
        </p>
      )}
    </div>
  );
}
