"use client";

import {
  ChevronDown, Loader2, Brain, Building2, FileText, RefreshCw,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
} from "@/components/ui/dropdown-menu";
import { api } from "@/lib/api";
import { STATUS_OPTIONS } from "./jobs-helpers";

interface BulkActionToolbarProps {
  selectedCount: number;
  bulkLoading: boolean;
  bulkError: string | null;
  bulkProgress: { current: number; total: number; action: string } | null;
  onBulkAction: (action: string, fn: (id: number) => Promise<unknown>) => void;
  onClear: () => void;
}

export function BulkActionToolbar(props: BulkActionToolbarProps) {
  const { selectedCount, bulkLoading, bulkError, bulkProgress, onBulkAction, onClear } = props;

  if (selectedCount === 0) return null;

  return (
    <div className="flex flex-wrap items-center gap-2 rounded-lg border border-border bg-muted/30 p-2.5">
      <span className="text-sm font-medium">
        {selectedCount} selected on this page
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
              onClick={() => onBulkAction(`Set ${opt.label}`, (id) => api.jobs.update(id, { status: opt.value }))}
            >
              {opt.label}
            </DropdownMenuItem>
          ))}
          <DropdownMenuSeparator />
          <DropdownMenuItem
            onClick={() => onBulkAction("Reject", (id) => api.jobs.update(id, { status: "rejected" }))}
          >
            Reject
          </DropdownMenuItem>
          <DropdownMenuItem
            onClick={() => onBulkAction("Skip", (id) => api.jobs.skip(id))}
          >
            Skip
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      <Button
        variant="outline"
        size="sm"
        disabled={bulkLoading}
        onClick={() => onBulkAction("AI Analysis", (id) => api.jobs.analysis.run(id))}
      >
        <Brain className="size-3.5" />
        Run Analysis
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={bulkLoading}
        onClick={() => onBulkAction("Company Research", (id) => api.jobs.companyResearch.run(id))}
      >
        <Building2 className="size-3.5" />
        Run Research
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={bulkLoading}
        title="Run AI Analysis + Company Research for each selected job"
        onClick={() => onBulkAction("Analysis + Research", async (id) => {
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
        onClick={() => onBulkAction("Refilter & Rescore", (id) => api.jobs.refilterRescore({ job_ids: [id] }))}
      >
        <RefreshCw className="size-3.5" />
        Refilter & Rescore
      </Button>
      <Button
        variant="outline"
        size="sm"
        disabled={bulkLoading}
        onClick={() => onBulkAction("Generate Resume", (id) => api.resumes.generate(id))}
      >
        <FileText className="size-3.5" />
        Gen Resume
      </Button>
      <Button
        variant="ghost"
        size="sm"
        onClick={onClear}
      >
        Clear
      </Button>
    </div>
  );
}
