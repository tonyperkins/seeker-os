"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { RefreshCw, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type RefilterRescoreResult } from "@/lib/api";

interface RefilterRescoreButtonProps {
  jobIds?: number[];
  runId?: string;
  variant?: "default" | "outline" | "ghost" | "secondary";
  size?: "default" | "sm" | "lg" | "icon";
  label?: string;
  summaryPosition?: "inline" | "below" | "none";
  onDone?: (results: RefilterRescoreResult[]) => void;
  onError?: (error: string) => void;
}

export function RefilterRescoreButton({
  jobIds,
  runId,
  variant = "outline",
  size = "sm",
  label = "Refilter & Rescore",
  summaryPosition = "inline",
  onDone,
  onError,
}: RefilterRescoreButtonProps) {
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [summary, setSummary] = useState<string | null>(null);
  const router = useRouter();

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
      const scoresChanged = results.filter((r) => r.score_changed).length;
      const statusChanged = results.filter((r) => r.status_changed).length;
      const researchCount = results.filter((r) => r.research_applied).length;

      const parts: string[] = [`${results.length} jobs`];
      if (scoresChanged > 0) parts.push(`${scoresChanged} score${scoresChanged > 1 ? "s" : ""} changed`);
      if (statusChanged > 0) parts.push(`${statusChanged} status changed`);
      if (failed > 0) parts.push(`${failed} filtered out`);
      if (researchCount > 0) parts.push(`${researchCount} research applied`);
      if (parts.length === 1) parts.push("no changes");

      setSummary(parts.join(" · "));
      onDone?.(results);
      router.refresh();
    } catch (err) {
      const message = err instanceof Error ? err.message : "Failed to refilter & rescore";
      setError(message);
      onError?.(message);
    } finally {
      setLoading(false);
    }
  }

  const summaryEl = (
    <>
      {error && <span className="text-xs text-destructive">{error}</span>}
      {summary && !error && (
        <span className="text-xs text-muted-foreground animate-in fade-in duration-300">{summary}</span>
      )}
    </>
  );

  if (summaryPosition === "none") {
    return (
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
    );
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
      {summaryEl}
    </div>
  );
}
