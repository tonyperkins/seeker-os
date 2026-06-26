"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent } from "@/components/ui/card";
import { api, type JobDetail } from "@/lib/api";

export function ScoreBadges({ initialJob }: { initialJob: JobDetail }) {
  const [job, setJob] = useState<JobDetail>(initialJob);

  useEffect(() => {
    function refresh() {
      api.jobs.get(initialJob.id).then(setJob).catch(() => {});
    }
    window.addEventListener("company-research-complete", refresh);
    window.addEventListener("analysis-complete", refresh);
    return () => {
      window.removeEventListener("company-research-complete", refresh);
      window.removeEventListener("analysis-complete", refresh);
    };
  }, [initialJob.id]);

  const baseScore = job.score;
  const researchDelta = job.research_delta;
  const hasResearch = job.research_adjusted_score != null;
  const hasAnalysis = job.analysis_verdict != null;

  // Use backend-computed net_score (verdict-capped composite).
  // Fallback to base + research when net_score hasn't been computed yet
  // (e.g. un-analyzed job, or pre-migration DB row).
  const netScore = job.net_score != null
    ? job.net_score
    : baseScore != null
      ? Math.max(0, Math.min(10, baseScore + researchDelta))
      : null;

  function deltaColor(delta: number) {
    if (delta < 0) return "text-amber-600";
    if (delta > 0) return "text-emerald-600";
    return "text-muted-foreground";
  }

  function deltaStr(delta: number) {
    return delta > 0 ? `+${delta.toFixed(1)}` : delta.toFixed(1);
  }

  return (
    <div className="flex flex-col gap-2 items-end">
      <div className="flex items-center gap-2">
        <Badge variant="outline">{job.status}</Badge>
        {netScore != null && (
          <Badge variant="default" className="text-base">
            Net: {netScore.toFixed(1)}
          </Badge>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2 w-full">
        {/* Base Score */}
        <Card className="py-3">
          <CardContent className="flex flex-col items-center gap-0.5 px-3">
            <span className="text-xs text-muted-foreground">Base Score</span>
            <span className="text-lg font-bold">
              {baseScore != null ? baseScore.toFixed(1) : "—"}
            </span>
          </CardContent>
        </Card>

        {/* Research Modifier */}
        <Card className="py-3">
          <CardContent className="flex flex-col items-center gap-0.5 px-3">
            <span className="text-xs text-muted-foreground">Research</span>
            {hasResearch ? (
              <span className={`text-lg font-bold ${deltaColor(researchDelta)}`}>
                {deltaStr(researchDelta)}
              </span>
            ) : (
              <span className="text-lg font-bold text-muted-foreground">—</span>
            )}
          </CardContent>
        </Card>

        {/* AI Analysis Verdict (caps the composite score) */}
        <Card className="py-3">
          <CardContent className="flex flex-col items-center gap-0.5 px-3">
            <span className="text-xs text-muted-foreground">AI Verdict</span>
            {hasAnalysis ? (
              <>
                <span className={`text-lg font-bold ${
                  job.analysis_verdict === "APPLY" ? "text-emerald-600"
                  : job.analysis_verdict === "SKIP" ? "text-amber-600"
                  : "text-muted-foreground"
                }`}>
                  {job.analysis_verdict}
                </span>
              </>
            ) : (
              <span className="text-lg font-bold text-muted-foreground">—</span>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
