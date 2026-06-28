"use client";

import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { RunPipelineButton } from "@/components/run-pipeline-button";
import { formatDateTime } from "@/lib/date";

export interface RunStripData {
  started_at: string;
  cards_new: number;
  jobs_ready: number;
}

export function RunStrip({ lastRun }: { lastRun: RunStripData | null }) {
  return (
    <div className="flex flex-col gap-0">
      <div className="flex items-center gap-4 rounded-lg border bg-card px-4 py-2.5">
        <RunPipelineButton compact />
        {lastRun && (
          <span className="text-sm text-muted-foreground">
            Last run: {formatDateTime(lastRun.started_at)} ·{" "}
            <span className="font-mono font-medium text-foreground">{lastRun.cards_new}</span> new ·{" "}
            <span className="font-mono font-medium text-foreground">{lastRun.jobs_ready}</span> ready
          </span>
        )}
        <Link
          href="/queries"
          className="ml-auto text-sm text-muted-foreground transition-colors hover:text-foreground"
        >
          Manage queries
          <ArrowRight className="ml-1 inline size-3.5" />
        </Link>
      </div>
    </div>
  );
}
