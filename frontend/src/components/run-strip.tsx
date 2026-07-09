"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, ChevronDown, Clock, XCircle } from "lucide-react";
import { RunPipelineButton } from "@/components/run-pipeline-button";
import { RecentRunRow } from "@/components/recent-run-row";
import { formatDateTime } from "@/lib/date";
import type { FunnelStage, PipelineRunRecord } from "@/lib/api";

export interface RunStripData {
  started_at: string;
  cards_new: number;
  jobs_ready: number;
}

const STAGE_COLORS: Record<number, string> = {
  1: "bg-sky-500 dark:bg-sky-600",
  2: "bg-indigo-500 dark:bg-indigo-600",
  4: "bg-purple-500 dark:bg-purple-600",
};

function FunnelChart({ stages }: { stages: FunnelStage[] }) {
  const ordered = [...stages].sort((a, b) => a.tier - b.tier);
  const max = ordered[0]?.count || 1;

  return (
    <div className="flex flex-col gap-3">
      {ordered.map((stage) => {
        const pct = max > 0 ? (stage.count / max) * 100 : 0;
        const color = STAGE_COLORS[stage.tier] || "bg-primary";
        return (
          <div key={stage.label} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between text-sm">
              <Link
                href={`/jobs?min_tier=${stage.tier}`}
                className="text-muted-foreground transition-opacity hover:opacity-70"
              >
                {stage.label}
              </Link>
              <span className="font-mono text-xs">
                <span className="font-semibold text-foreground">{stage.count}</span>
                <span className="ml-1.5 text-muted-foreground">
                  {pct > 0 ? `${Math.round(pct)}%` : "0%"}
                </span>
              </span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all ${color}`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export function RunStrip({
  lastRun,
  jdFetchPct,
  jdFetchTotal,
  jdFetchSuccess,
  runs,
  funnelStages,
  rejectedCount,
}: {
  lastRun: RunStripData | null;
  jdFetchPct?: number;
  jdFetchTotal?: number;
  jdFetchSuccess?: number;
  runs?: PipelineRunRecord[];
  funnelStages?: FunnelStage[];
  rejectedCount?: number;
}) {
  const [expanded, setExpanded] = useState(false);
  const hasDetails = (runs && runs.length > 0) || (funnelStages && funnelStages.length > 0);

  return (
    <div className="flex flex-col gap-0">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1.5 rounded-lg border bg-card px-4 py-2.5">
        <RunPipelineButton compact />
        {lastRun && (
          <span className="text-sm text-muted-foreground">
            Last run: {formatDateTime(lastRun.started_at)} ·{" "}
            <span className="font-mono font-medium text-foreground">{lastRun.cards_new}</span> new ·{" "}
            <span className="font-mono font-medium text-foreground">{lastRun.jobs_ready}</span> produced ready
          </span>
        )}
        {jdFetchTotal != null && jdFetchTotal > 0 && (
          <span className="text-sm text-muted-foreground">
            JD fetch:{" "}
            <span className="font-mono font-medium text-foreground">{jdFetchSuccess}/{jdFetchTotal}</span>
            <span className="ml-1 font-mono text-xs">({jdFetchPct}%)</span>
          </span>
        )}
        <span className="flex items-center gap-1.5 text-sm text-muted-foreground/60">
          <Clock className="size-3.5" />
          Next run: <span className="font-mono">—</span>
        </span>
        <div className="ml-auto flex items-center gap-3">
          {hasDetails && (
            <button
              onClick={() => setExpanded((v) => !v)}
              className="flex items-center gap-1 text-sm text-muted-foreground transition-colors hover:text-foreground"
            >
              {expanded ? "Hide details" : "Details"}
              <ChevronDown className={`size-4 transition-transform ${expanded ? "rotate-180" : ""}`} />
            </button>
          )}
          <Link
            href="/queries"
            className="text-sm text-muted-foreground transition-colors hover:text-foreground"
          >
            Manage queries
            <ArrowRight className="ml-1 inline size-3.5" />
          </Link>
        </div>
      </div>

      {expanded && hasDetails && (
        <div className="mt-2 grid gap-4 rounded-lg border bg-card p-4 lg:grid-cols-[1.1fr_1fr]">
          {/* Recent runs — scrollable */}
          <div className="flex flex-col gap-2">
            <h3 className="text-sm font-semibold text-muted-foreground">Recent Pipeline Runs</h3>
            {runs && runs.length > 0 ? (
              <div className="flex flex-col divide-y divide-border overflow-y-auto max-h-56 min-h-0">
                {runs.map((run) => (
                  <RecentRunRow key={run.id} run={run} />
                ))}
              </div>
            ) : (
              <p className="py-4 text-center text-sm text-muted-foreground">
                No pipeline runs yet.
              </p>
            )}
          </div>

          {/* Pipeline funnel */}
          {funnelStages && funnelStages.length > 0 ? (
            <div className="flex flex-col gap-3">
              <h3 className="text-sm font-semibold text-muted-foreground">Pipeline Funnel</h3>
              <FunnelChart stages={funnelStages} />
              <div className="flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-3 text-sm">
                <div className="flex items-center gap-2">
                  <XCircle className="size-4 text-destructive" />
                  <span className="text-muted-foreground">Rejected</span>
                  <span className="font-mono font-semibold">{rejectedCount ?? 0}</span>
                </div>
              </div>
            </div>
          ) : (
            <div className="flex items-center justify-center">
              <p className="text-sm text-muted-foreground">No funnel data yet.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
