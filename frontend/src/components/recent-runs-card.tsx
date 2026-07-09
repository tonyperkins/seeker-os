"use client";

import { useState } from "react";
import { ChevronLeft, ChevronRight } from "lucide-react";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/collapsible-card";
import { RecentRunRow } from "@/components/recent-run-row";
import type { PipelineRunRecord } from "@/lib/api";

const PAGE_SIZE = 3;

export function RecentRunsCard({ runs }: { runs: PipelineRunRecord[] }) {
  const [page, setPage] = useState(0);
  const totalPages = Math.ceil(runs.length / PAGE_SIZE);
  const pageRuns = runs.slice(page * PAGE_SIZE, (page + 1) * PAGE_SIZE);

  return (
    <CollapsibleCard
      title="Recent Pipeline Runs"
      description="Latest pipeline execution history"
      storageKey="dash-recent-runs"
      className="h-full"
      contentClassName="flex flex-1 flex-col min-h-0"
      action={totalPages > 1 ? (
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 0}
            onClick={() => setPage((p) => Math.max(0, p - 1))}
          >
            <ChevronLeft className="size-4" />
          </Button>
          <span className="text-xs text-muted-foreground px-1">
            {page + 1}/{totalPages}
          </span>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages - 1}
            onClick={() => setPage((p) => Math.min(totalPages - 1, p + 1))}
          >
            <ChevronRight className="size-4" />
          </Button>
        </div>
      ) : undefined}
    >
      {runs.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No pipeline runs yet.
        </p>
      ) : (
        <div className="flex flex-col divide-y divide-border overflow-x-hidden min-h-0">
          {pageRuns.map((run) => (
            <RecentRunRow key={run.id} run={run} />
          ))}
        </div>
      )}
    </CollapsibleCard>
  );
}
