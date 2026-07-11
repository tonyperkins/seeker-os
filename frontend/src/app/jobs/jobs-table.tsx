"use client";

import { useRouter } from "next/navigation";
import {
  Pin, Brain, Building2, FileText, CheckSquare, Square,
  ArrowUpDown, ArrowUp, ArrowDown, Users,
} from "lucide-react";
import {
  Card, CardContent,
} from "@/components/ui/card";
import {
  Table, TableBody, TableCell, TableHead, TableHeader, TableRow,
} from "@/components/ui/table";
import { ErrorBanner } from "@/components/error-banner";
import { Loader2 } from "lucide-react";
import type { JobSortKey, JobSummary } from "@/lib/api";
import { statusIcon, formatComp, statusRowClass } from "./jobs-helpers";

interface JobsTableProps {
  jobs: JobSummary[] | null;
  loading: boolean;
  error: string | null;
  sortKey: JobSortKey;
  sortDir: "asc" | "desc";
  selectedIds: Set<number>;
  allSelected: boolean;
  onToggleSort: (key: JobSortKey) => void;
  onToggleJob: (id: number) => void;
  onToggleAll: () => void;
}

export function JobsTable(props: JobsTableProps) {
  const {
    jobs, loading, error, sortKey, sortDir,
    selectedIds, allSelected, onToggleSort, onToggleJob, onToggleAll,
  } = props;

  const router = useRouter();
  const displayedJobs = jobs ?? [];

  function sortIcon(key: JobSortKey) {
    if (sortKey !== key) return <ArrowUpDown className="size-3 text-muted-foreground/50" />;
    return sortDir === "asc" ? <ArrowUp className="size-3 text-primary" /> : <ArrowDown className="size-3 text-primary" />;
  }

  return (
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
          <div className="flex flex-col">
            <div className="overflow-x-auto">
            <Table aria-label="Jobs table">
              <TableHeader>
                <TableRow>
                  <TableHead className="w-10 shrink-0" aria-sort={sortKey === "score" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={onToggleAll} className="flex items-center" aria-label={allSelected ? "Deselect all jobs on this page" : "Select all jobs on this page"} aria-pressed={allSelected}>
                      {allSelected ? (
                        <CheckSquare className="size-4 text-primary" />
                      ) : (
                        <Square className="size-4 text-muted-foreground" />
                      )}
                    </button>
                  </TableHead>
                  <TableHead className="w-14 shrink-0" aria-sort={sortKey === "score" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("score")} className="flex items-center gap-1 hover:text-foreground">
                      Score {sortIcon("score")}
                    </button>
                  </TableHead>
                  <TableHead className="w-28 shrink-0" aria-sort={sortKey === "status" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("status")} className="flex items-center gap-1 hover:text-foreground">
                      Status {sortIcon("status")}
                    </button>
                  </TableHead>
                  <TableHead className="w-20 shrink-0" aria-sort={sortKey === "run_id" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("run_id")} className="flex items-center gap-1 hover:text-foreground">
                      Run {sortIcon("run_id")}
                    </button>
                  </TableHead>
                  <TableHead className="min-w-[160px] max-w-[260px]" aria-sort={sortKey === "title" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("title")} className="flex items-center gap-1 hover:text-foreground">
                      Title {sortIcon("title")}
                    </button>
                  </TableHead>
                  <TableHead className="min-w-[100px] max-w-[180px]" aria-sort={sortKey === "company" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("company")} className="flex items-center gap-1 hover:text-foreground">
                      Company {sortIcon("company")}
                    </button>
                  </TableHead>
                  <TableHead className="w-28 shrink-0" aria-sort={sortKey === "comp" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("comp")} className="flex items-center gap-1 hover:text-foreground">
                      Comp {sortIcon("comp")}
                    </button>
                  </TableHead>
                  <TableHead className="min-w-[80px] max-w-[140px]" aria-sort={sortKey === "location" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("location")} className="flex items-center gap-1 hover:text-foreground">
                      Location {sortIcon("location")}
                    </button>
                  </TableHead>
                  <TableHead className="w-24 shrink-0" aria-sort={sortKey === "ats" ? (sortDir === "asc" ? "ascending" : "descending") : undefined}>
                    <button type="button" onClick={() => onToggleSort("ats")} className="flex items-center gap-1 hover:text-foreground">
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
                    onKeyDown={(e) => {
                      if (e.key === "Enter") {
                        e.preventDefault();
                        router.push(`/jobs/${job.id}`);
                      }
                    }}
                    tabIndex={0}
                    role="link"
                    aria-label={`${job.title} at ${job.company}, status: ${job.status}`}
                  >
                    <TableCell className="w-10 shrink-0" onClick={(e) => e.stopPropagation()}>
                      <button
                        type="button"
                        onClick={() => onToggleJob(job.id)}
                        className="flex items-center"
                        aria-label={`Select ${job.title} at ${job.company}`}
                        aria-pressed={selectedIds.has(job.id)}
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
                        <span title={job.net_score != null && job.net_score !== job.score ? `Base score ${job.score} → ${job.net_score.toFixed(1)} after company research` : undefined}>
                          {job.score != null ? job.score : "—"}
                        </span>
                        {job.net_score != null && job.net_score !== job.score && (
                          <span className="text-xs text-muted-foreground" title={`Base score ${job.score} → ${job.net_score.toFixed(1)} after company research`}>
                            → {job.net_score.toFixed(1)}
                          </span>
                        )}
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap">
                      <div className="flex items-center gap-1" title={job.reject_reason ? (job.reject_details ? `Manually rejected: ${job.reject_reason}` : job.reject_reason) : job.status}>
                        {statusIcon(job.status, !!job.reject_details)}
                        <span title={job.has_analysis ? `Analysis: ${job.analysis_verdict ?? "done"}` : "No analysis yet"} className="contents">
                          <Brain className={`size-3.5 ${
                            !job.has_analysis
                              ? "text-muted-foreground/35"
                              : job.analysis_verdict === "APPLY"
                                ? "text-emerald-500"
                                : job.analysis_verdict === "CONDITIONAL"
                                  ? "text-amber-500"
                                  : job.analysis_verdict === "MONITOR"
                                    ? "text-sky-500"
                                    : job.analysis_verdict === "SKIP"
                                      ? "text-red-500"
                                      : "text-primary"
                          }`} aria-hidden={!job.has_analysis} role={job.has_analysis ? "img" : undefined} aria-label={job.has_analysis ? `Analysis: ${job.analysis_verdict ?? "done"}` : undefined} />
                        </span>
                        <span title={job.has_research ? "Company research done" : "No company research"} className="contents">
                          <Building2 className={`size-3.5 ${job.has_research ? "text-primary" : "text-muted-foreground/35"}`} aria-hidden={!job.has_research} role={job.has_research ? "img" : undefined} aria-label={job.has_research ? "Research done" : undefined} />
                        </span>
                        <span title={job.has_resume ? "Resume generated" : "No resume yet"} className="contents">
                          <FileText className={`size-3.5 ${job.has_resume ? "text-primary" : "text-muted-foreground/35"}`} aria-hidden={!job.has_resume} role={job.has_resume ? "img" : undefined} aria-label={job.has_resume ? "Resume generated" : undefined} />
                        </span>
                        <span title={job.has_recruiter ? `Recruiter: ${job.recruiter_source ?? "contact"}` : "No recruiter contact"} className="contents">
                          <Users className={`size-3.5 ${job.has_recruiter ? "text-primary" : "text-muted-foreground/35"}`} aria-hidden={!job.has_recruiter} role={job.has_recruiter ? "img" : undefined} aria-label={job.has_recruiter ? `Recruiter: ${job.recruiter_source ?? "contact"}` : undefined} />
                        </span>
                      </div>
                    </TableCell>
                    <TableCell className="whitespace-nowrap font-mono text-xs text-muted-foreground">
                      {job.run_id ?? "—"}
                    </TableCell>
                    <TableCell className="max-w-[260px]">
                      <div className="flex items-center gap-1.5">
                        {job.is_pinned && <span title="Pinned" className="contents"><Pin className="size-3.5 shrink-0 text-amber-500" /></span>}
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
            <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-t border-border px-4 py-2 text-[11px] text-muted-foreground">
              <span className="font-semibold uppercase tracking-wider text-muted-foreground/60">Indicators:</span>
              <span className="flex items-center gap-1"><Brain className="size-3" /> Analysis</span>
              <span className="flex items-center gap-1"><Building2 className="size-3" /> Research</span>
              <span className="flex items-center gap-1"><FileText className="size-3" /> Resume</span>
              <span className="flex items-center gap-1"><Users className="size-3" /> Recruiter</span>
              <span className="flex items-center gap-1"><Pin className="size-3 text-amber-500" /> Pinned</span>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}
