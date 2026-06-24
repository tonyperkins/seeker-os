"use client";

import { Suspense, useEffect, useState, useCallback, useMemo } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { Search, Loader2, AlertCircle, Pin } from "lucide-react";
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  CardDescription,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { api, type JobSummary } from "@/lib/api";

const STATUS_OPTIONS = [
  { value: "", label: "All statuses" },
  { value: "ready", label: "Ready" },
  { value: "rejected", label: "Rejected" },
  { value: "discovered", label: "Discovered" },
  { value: "filtered", label: "Filtered" },
  { value: "jd_fetched", label: "JD Fetched" },
  { value: "reviewing", label: "Reviewing" },
  { value: "interested", label: "Interested" },
  { value: "applied", label: "Applied" },
  { value: "skipped", label: "Skipped" },
];

function statusBadgeVariant(status: string) {
  switch (status) {
    case "ready":
      return "default";
    case "rejected":
    case "filtered":
      return "destructive";
    case "reviewing":
    case "interested":
      return "secondary";
    case "applied":
      return "default";
    default:
      return "outline";
  }
}

function formatComp(min: number | null, max: number | null): string {
  if (min == null && max == null) return "—";
  const fmt = (n: number) => `$${(n / 1000).toFixed(0)}k`;
  if (min != null && max != null) return `${fmt(min)}–${fmt(max)}`;
  if (min != null) return `${fmt(min)}+`;
  return `≤${fmt(max as number)}`;
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

  const [status, setStatus] = useState<string>(searchParams.get("status") ?? "");
  const [minScore, setMinScore] = useState<string>(searchParams.get("min_score") ?? "");
  const [minTier, setMinTier] = useState<string>(searchParams.get("min_tier") ?? "");
  const [company, setCompany] = useState<string>(searchParams.get("company") ?? "");
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const params: { status?: string; min_score?: number; min_tier?: number; company?: string; limit?: number } = {
        limit: 200,
      };
      if (status) params.status = status;
      const mt = parseInt(minTier, 10);
      if (!isNaN(mt)) params.min_tier = mt;
      const ms = parseInt(minScore, 10);
      if (!isNaN(ms)) params.min_score = ms;
      if (company.trim()) params.company = company.trim();
      const data = await api.jobs.list(params);
      setJobs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, [status, minScore, minTier, company]);

  useEffect(() => {
    // Fetch on mount and when filters change — legitimate data-fetching effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchJobs();
  }, [fetchJobs]);

  // Keep URL in sync (shallow)
  useEffect(() => {
    const params = new URLSearchParams();
    if (status) params.set("status", status);
    if (minTier) params.set("min_tier", minTier);
    if (minScore) params.set("min_score", minScore);
    if (company) params.set("company", company);
    const qs = params.toString();
    router.replace(qs ? `/jobs?${qs}` : "/jobs", { scroll: false });
  }, [status, minTier, minScore, company, router]);

  const sortedJobs = useMemo(() => {
    if (!jobs) return [];
    return [...jobs].sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  }, [jobs]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Jobs</h1>
        <p className="text-sm text-muted-foreground">
          All discovered jobs with filtering and search.
        </p>
      </div>

      {/* Filters */}
      <Card>
        <CardHeader>
          <CardTitle>Filters</CardTitle>
          <CardDescription>Narrow down the job list</CardDescription>
        </CardHeader>
        <CardContent>
          <div className="flex flex-wrap items-end gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">Status</label>
              <select
                value={status}
                onChange={(e) => setStatus(e.target.value)}
                className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              >
                {STATUS_OPTIONS.map((opt) => (
                  <option key={opt.value} value={opt.value} className="bg-background text-foreground">
                    {opt.label}
                  </option>
                ))}
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">Min tier</label>
              <select
                value={minTier}
                onChange={(e) => setMinTier(e.target.value)}
                className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              >
                <option value="" className="bg-background text-foreground">Any tier</option>
                <option value="2" className="bg-background text-foreground">Passed filters</option>
                <option value="4" className="bg-background text-foreground">Passed scoring</option>
              </select>
            </div>

            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">Min score</label>
              <Input
                type="number"
                min={0}
                max={100}
                placeholder="0"
                value={minScore}
                onChange={(e) => setMinScore(e.target.value)}
                className="w-24"
              />
            </div>

            <div className="flex flex-1 flex-col gap-1.5">
              <label className="text-xs font-medium text-muted-foreground">Company search</label>
              <div className="relative">
                <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  type="text"
                  placeholder="Search by company name…"
                  value={company}
                  onChange={(e) => setCompany(e.target.value)}
                  className="pl-8"
                />
              </div>
            </div>

            <Button variant="outline" size="sm" onClick={fetchJobs} disabled={loading}>
              {loading ? <Loader2 className="animate-spin" /> : <Search />}
              Refresh
            </Button>
          </div>
        </CardContent>
      </Card>

      {/* Table */}
      <Card>
        <CardContent className="p-0">
          {error ? (
            <div className="flex items-center gap-2 p-6 text-sm text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              {error}
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
                    <TableHead className="w-14 shrink-0">Score</TableHead>
                    <TableHead className="min-w-[160px] max-w-[260px]">Title</TableHead>
                    <TableHead className="min-w-[100px] max-w-[180px]">Company</TableHead>
                    <TableHead className="w-24 shrink-0">Status</TableHead>
                    <TableHead className="w-28 shrink-0">Comp</TableHead>
                    <TableHead className="min-w-[80px] max-w-[140px]">Location</TableHead>
                    <TableHead className="w-24 shrink-0">ATS</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {sortedJobs.map((job) => (
                    <TableRow
                      key={job.id}
                      className="cursor-pointer"
                      onClick={() => router.push(`/jobs/${job.id}`)}
                    >
                      <TableCell className="whitespace-nowrap font-mono font-medium">
                        {job.score != null ? job.score : "—"}
                      </TableCell>
                      <TableCell className="max-w-[260px]">
                        <div className="flex items-center gap-1.5">
                          {job.is_pinned && <Pin className="size-3.5 shrink-0 text-amber-500" />}
                          <span className="truncate font-medium">{job.title}</span>
                        </div>
                      </TableCell>
                      <TableCell className="max-w-[180px] truncate text-muted-foreground">{job.company}</TableCell>
                      <TableCell className="whitespace-nowrap">
                        <Badge variant={statusBadgeVariant(job.status)}>{job.status}</Badge>
                      </TableCell>
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
