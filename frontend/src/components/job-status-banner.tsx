"use client";

import { useEffect, useState } from "react";
import {
  CheckCircle2,
  XCircle,
  UserX,
  MinusCircle,
  Send,
  CircleDashed,
  Filter,
  FileSearch,
  Eye,
  Star,
  RotateCcw,
} from "lucide-react";
import { api, type JobDetail } from "@/lib/api";
import { cn } from "@/lib/utils";

interface StatusConfig {
  label: string;
  icon: typeof CheckCircle2;
  className: string;
  iconClassName: string;
}

const STATUS_CONFIG: Record<string, StatusConfig> = {
  rejected: {
    label: "Rejected",
    icon: XCircle,
    className: "bg-red-500/10 border-red-500/30 text-red-700 dark:text-red-400",
    iconClassName: "text-red-500",
  },
  skipped: {
    label: "Skipped",
    icon: MinusCircle,
    className: "bg-muted/40 border-border text-muted-foreground",
    iconClassName: "text-muted-foreground",
  },
  applied: {
    label: "Applied",
    icon: Send,
    className: "bg-violet-500/10 border-violet-500/30 text-violet-700 dark:text-violet-400",
    iconClassName: "text-violet-500",
  },
  interested: {
    label: "Interested",
    icon: Star,
    className: "bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-400",
    iconClassName: "text-amber-500",
  },
  reviewing: {
    label: "Reviewing",
    icon: Eye,
    className: "bg-blue-500/10 border-blue-500/30 text-blue-700 dark:text-blue-400",
    iconClassName: "text-blue-500",
  },
  ready: {
    label: "Ready",
    icon: CheckCircle2,
    className: "bg-emerald-500/10 border-emerald-500/30 text-emerald-700 dark:text-emerald-400",
    iconClassName: "text-emerald-500",
  },
  discovered: {
    label: "Discovered",
    icon: CircleDashed,
    className: "bg-amber-500/10 border-amber-500/30 text-amber-700 dark:text-amber-400",
    iconClassName: "text-amber-500",
  },
  filtered: {
    label: "Filtered",
    icon: Filter,
    className: "bg-orange-500/10 border-orange-500/30 text-orange-700 dark:text-orange-400",
    iconClassName: "text-orange-500",
  },
  jd_fetched: {
    label: "JD Fetched",
    icon: FileSearch,
    className: "bg-blue-500/10 border-blue-500/30 text-blue-700 dark:text-blue-400",
    iconClassName: "text-blue-500",
  },
};

export function JobStatusBanner({ initialJob }: { initialJob: JobDetail }) {
  const [job, setJob] = useState<JobDetail>(initialJob);

  useEffect(() => {
    function refresh() {
      api.jobs.get(initialJob.id).then(setJob).catch(() => {});
    }
    window.addEventListener("analysis-complete", refresh);
    window.addEventListener("company-research-complete", refresh);
    window.addEventListener("job-status-changed", refresh);
    return () => {
      window.removeEventListener("analysis-complete", refresh);
      window.removeEventListener("company-research-complete", refresh);
      window.removeEventListener("job-status-changed", refresh);
    };
  }, [initialJob.id]);

  const config = STATUS_CONFIG[job.status] ?? {
    label: job.status,
    icon: CircleDashed,
    className: "bg-muted/40 border-border text-muted-foreground",
    iconClassName: "text-muted-foreground",
  };

  const Icon = config.icon;
  const isRejected = job.status === "rejected";
  const isOverridden = job.overridden_at != null;

  return (
    <div className={cn("flex items-center gap-3 rounded-lg border px-4 py-2.5", config.className)}>
      <Icon className={cn("size-5 shrink-0", config.iconClassName)} />
      <div className="flex flex-col gap-0.5">
        <span className="text-sm font-semibold uppercase tracking-wide">
          {config.label}
        </span>
        {isRejected && job.reject_reason && (
          <span className="text-xs opacity-80">
            {job.reject_reason}
            {job.original_reject_reason && isOverridden && " (overridden)"}
          </span>
        )}
        {isRejected && !job.reject_reason && isOverridden && (
          <span className="text-xs opacity-80">Rejection overridden</span>
        )}
        {job.status === "skipped" && job.reject_reason && (
          <span className="text-xs opacity-80">{job.reject_reason}</span>
        )}
      </div>
      {isOverridden && !isRejected && (
        <div className="ml-auto flex items-center gap-1.5 text-xs opacity-70">
          <RotateCcw className="size-3.5" />
          <span>Overridden</span>
        </div>
      )}
    </div>
  );
}
