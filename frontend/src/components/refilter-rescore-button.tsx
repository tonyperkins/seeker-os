"use client";

import { useState } from "react";
import { RefreshCw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type RefilterRescoreResult } from "@/lib/api";

interface RefilterRescoreButtonProps {
  jobIds?: number[];
  runId?: string;
  variant?: "default" | "outline" | "ghost" | "secondary";
  size?: "default" | "sm" | "lg" | "icon";
  label?: string;
  onDone?: (results: RefilterRescoreResult[]) => void;
}

export function RefilterRescoreButton({
  jobIds,
  runId,
  variant = "outline",
  size = "sm",
  label = "Refilter & Rescore",
  onDone,
}: RefilterRescoreButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);

  async function handleClick() {
    setLoading(true);
    setError(null);
    setSummary(null);
    try {
      const results = await api.jobs.refilterRescore({
        job_ids: jobIds,
        run_id: runId,
      });
      const passed = results.filter((r) => r.filter_passed).length;
      const failed = results.length - passed;
      setSummary(`${passed} passed, ${failed} filtered` + (results.some((r) => r.research_applied) ? " (research applied)" : ""));
      onDone?.(results);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to refilter & rescore");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex items-center gap-2">
      <Button
        variant={variant}
        size={size}
        disabled={loading}
        onClick={handleClick}
      >
        {loading ? (
          <Loader2 className="size-3.5 animate-spin" />
        ) : (
          <RefreshCw className="size-3.5" />
        )}
        {label}
      </Button>
      {error && <span className="text-xs text-destructive">{error}</span>}
      {summary && !error && (
        <span className="text-xs text-muted-foreground">{summary}</span>
      )}
    </div>
  );
}
