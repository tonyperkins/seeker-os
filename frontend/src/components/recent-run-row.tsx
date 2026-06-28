"use client";

import { useState } from "react";
import Link from "next/link";
import { CheckCircle2, Clock, XCircle } from "lucide-react";
import { RefilterRescoreButton } from "@/components/refilter-rescore-button";
import { formatDateTime } from "@/lib/date";
import { type PipelineRunRecord, type RefilterRescoreResult } from "@/lib/api";

interface RecentRunRowProps {
  run: PipelineRunRecord;
}

export function RecentRunRow({ run }: RecentRunRowProps) {
  const [summary, setSummary] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  function buildSummary(results: RefilterRescoreResult[]) {
    const passed = results.filter((r) => r.filter_passed).length;
    const failed = results.length - passed;
    const scoresChanged = results.filter((r) => r.score_changed).length;
    const statusChanged = results.filter((r) => r.status_changed).length;
    const researchCount = results.filter((r) => r.research_applied).length;

    const parts: string[] = [`${results.length} jobs`];
    if (scoresChanged > 0) parts.push(`${scoresChanged} score${scoresChanged > 1 ? "s" : ""} changed`);
    if (statusChanged > 0) parts.push(`${statusChanged} status changed`);
    if (failed > 0) parts.push(`${failed} filtered out`);
    if (researchCount > 0) parts.push(`${researchCount} research applied`);
    if (parts.length === 1) parts.push("no changes");

    return parts.join(" · ");
  }

  return (
    <div className="flex flex-col gap-1 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md">
      <div className="flex items-center gap-3">
        <Link
          href={`/jobs?run_id=${run.run_id}&clear_filters=1`}
          className="flex flex-1 items-center gap-3 min-w-0"
        >
          {run.status === "completed" ? (
            <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />
          ) : run.status === "failed" ? (
            <XCircle className="size-4 shrink-0 text-destructive" />
          ) : (
            <Clock className="size-4 shrink-0 text-muted-foreground" />
          )}
          <div className="flex flex-col">
            <span className="text-muted-foreground">{formatDateTime(run.started_at)}</span>
            <span className="font-mono text-xs text-muted-foreground/70">
              {run.run_id.slice(0, 8)}
            </span>
          </div>
          <div className="ml-auto flex items-center gap-4 font-mono text-xs shrink-0">
            <div className="flex flex-col items-end">
              <span className="font-semibold">{run.cards_fetched}</span>
              <span className="text-muted-foreground/70">fetched</span>
            </div>
            <div className="flex flex-col items-end">
              <span className="font-semibold">{run.cards_new}</span>
              <span className="text-muted-foreground/70">new</span>
            </div>
            <div className="flex flex-col items-end">
              <span className="font-bold text-emerald-600 dark:text-emerald-400">{run.jobs_ready}</span>
              <span className="text-muted-foreground/70">ready</span>
            </div>
          </div>
        </Link>
        <RefilterRescoreButton
          runId={run.run_id}
          label=""
          size="icon"
          variant="ghost"
          summaryPosition="none"
          onDone={(results) => {
            setError(null);
            setSummary(buildSummary(results));
          }}
          onError={(message) => {
            setSummary(null);
            setError(message);
          }}
        />
      </div>
      {(error || summary) && (
        <div className="text-right text-xs text-muted-foreground animate-in fade-in duration-300">
          {error ? <span className="text-destructive">{error}</span> : summary}
        </div>
      )}
    </div>
  );
}
