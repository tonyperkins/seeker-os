"use client";

import { useState } from "react";
import { Play, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type PipelineRunSummary } from "@/lib/api";

export function RunPipelineButton() {
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PipelineRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);

  async function handleRun() {
    setLoading(true);
    setError(null);
    setResult(null);
    try {
      const summary = await api.pipeline.run({});
      setResult(summary);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to run pipeline");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <Button onClick={handleRun} disabled={loading} size="lg">
        {loading ? (
          <Loader2 className="animate-spin" />
        ) : (
          <Play />
        )}
        {loading ? "Running Pipeline…" : "Run Pipeline"}
      </Button>

      {error && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="flex items-start gap-2 rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-400">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">Pipeline complete — run {result.run_id.slice(0, 8)}</p>
            <p className="text-xs text-muted-foreground">
              {result.cards_fetched} fetched · {result.cards_new} new · {result.tier2_passed} passed T2 ·{" "}
              {result.tier4_scored} scored · {result.tier5_ready} ready
            </p>
          </div>
        </div>
      )}
    </div>
  );
}
