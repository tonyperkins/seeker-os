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
  const analysisDelta = job.analysis_delta;
  const hasAnalysis = job.analysis_verdict != null;

  const netScore = baseScore != null
    ? baseScore + researchDelta + analysisDelta
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
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Badge variant="outline">{job.status}</Badge>
        {netScore != null && (
          <Badge variant="default" className="text-base">
            Net: {netScore.toFixed(1)}
          </Badge>
        )}
      </div>
      <div className="grid grid-cols-3 gap-2">
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

        {/* AI Analysis Modifier */}
        <Card className="py-3">
          <CardContent className="flex flex-col items-center gap-0.5 px-3">
            <span className="text-xs text-muted-foreground">AI Analysis</span>
            {hasAnalysis ? (
              <>
                <span className={`text-lg font-bold ${deltaColor(analysisDelta)}`}>
                  {deltaStr(analysisDelta)}
                </span>
                <span className="text-xs text-muted-foreground">{job.analysis_verdict}</span>
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
