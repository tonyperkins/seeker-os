"use client";

import { useEffect, useState } from "react";
import { Badge } from "@/components/ui/badge";
import { api, type JobDetail } from "@/lib/api";

export function ScoreBadges({ initialJob }: { initialJob: JobDetail }) {
  const [job, setJob] = useState<JobDetail>(initialJob);

  useEffect(() => {
    function handleResearchComplete() {
      api.jobs.get(initialJob.id).then(setJob).catch(() => {});
    }
    window.addEventListener("company-research-complete", handleResearchComplete);
    return () => window.removeEventListener("company-research-complete", handleResearchComplete);
  }, [initialJob.id]);

  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline">{job.status}</Badge>
      {job.score != null && (
        <Badge variant="default" className="text-base">Score: {job.score}</Badge>
      )}
      {job.research_adjusted_score != null && (
        <Badge
          variant="default"
          className={`text-base ${job.research_delta < 0 ? "bg-amber-600 hover:bg-amber-600" : job.research_delta > 0 ? "bg-emerald-600 hover:bg-emerald-600" : ""}`}
        >
          Adjusted: {job.research_adjusted_score.toFixed(1)}
          {job.research_delta !== 0 && (
            <span className="text-xs ml-1 opacity-80">
              ({job.research_delta > 0 ? "+" : ""}{job.research_delta.toFixed(1)})
            </span>
          )}
        </Badge>
      )}
    </div>
  );
}
