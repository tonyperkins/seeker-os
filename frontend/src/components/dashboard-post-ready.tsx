import Link from "next/link";
import {
  ArrowRight,
  Users,
  Clock,
  FileText,
  AlertTriangle,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/collapsible-card";
import type { JobSummary } from "@/lib/api";

export const STATUS_LABELS: Record<string, string> = {
  reviewing: "Reviewing",
  interested: "Interested",
  applied: "Applied",
  engaged: "Engaged",
  company_rejected: "Company Rejected",
  withdrawn: "Withdrawn",
  offer_accepted: "Offer Accepted",
  offer_declined: "Offer Declined",
};

export function StaleBadge({ days, threshold = 14 }: { days: number; threshold?: number }) {
  if (days < threshold) return null;
  const isCritical = days >= threshold * 2;
  return (
    <Badge
      variant="outline"
      className={isCritical
        ? "border-red-500/50 text-red-600 dark:text-red-400"
        : "border-amber-500/50 text-amber-600 dark:text-amber-400"
      }
    >
      <Clock className="size-3" />
      {days}d stale
    </Badge>
  );
}

export function PipelineFunnel({ byStatus }: { byStatus: Record<string, number> }) {
  const funnelStages = [
    { status: "ready", label: "Ready", color: "bg-emerald-500" },
    { status: "reviewing", label: "Reviewing", color: "bg-sky-500" },
    { status: "interested", label: "Interested", color: "bg-sky-500" },
    { status: "applied", label: "Applied", color: "bg-violet-500" },
    { status: "engaged", label: "Engaged", color: "bg-violet-500" },
    { status: "offer_accepted", label: "Offer", color: "bg-amber-500" },
  ];

  const funnelCounts = funnelStages.map((s) => ({ ...s, count: byStatus[s.status] ?? 0 }));
  const funnelMax = Math.max(...funnelCounts.map((c) => c.count), 1);
  const funnelTotal = funnelCounts.reduce((sum, c) => sum + c.count, 0);

  if (funnelTotal === 0) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No pipeline data yet.
      </p>
    );
  }

  return (
    <div className="flex flex-col gap-3">
      {funnelCounts.map((stage) => {
        const pct = funnelMax > 0 ? (stage.count / funnelMax) * 100 : 0;
        return (
          <div key={stage.status} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between text-sm">
              <Link
                href={`/jobs?status=${stage.status}`}
                className="text-muted-foreground transition-opacity hover:opacity-70"
              >
                {stage.label}
              </Link>
              <span className="font-mono text-xs">
                <span className="font-semibold text-foreground">{stage.count}</span>
              </span>
            </div>
            <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all ${stage.color}`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
          </div>
        );
      })}
      <div className="border-t border-border pt-2 text-xs text-muted-foreground">
        Total in pipeline: <span className="font-mono font-semibold text-foreground">{funnelTotal}</span>
      </div>
    </div>
  );
}

export function ActiveApplicationsContent({ jobs }: { jobs: JobSummary[] }) {
  const activeStatuses = new Set(["applied", "engaged", "offer_accepted", "offer_declined"]);
  const active = jobs.filter((j) => activeStatuses.has(j.status));
  const rejectedCount = jobs.filter((j) => j.status === "company_rejected" || j.status === "withdrawn").length;

  const sorted = [...active].sort((a, b) => {
    const aDays = a.days_since_last_activity ?? 999;
    const bDays = b.days_since_last_activity ?? 999;
    return bDays - aDays;
  });

  return (
    <div className="flex flex-col min-h-0">
      {rejectedCount > 0 && (
        <div className="mb-2 shrink-0 rounded-md bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
          <span className="font-mono font-medium text-foreground">{rejectedCount}</span> rejected · auto-archived
        </div>
      )}
      {sorted.length > 0 ? (
        <div className="flex flex-col divide-y divide-border overflow-y-auto overflow-x-hidden max-h-72 min-h-0">
          {sorted.map((job) => {
            const days = job.days_since_last_activity ?? 0;
            return (
              <Link
                key={job.id}
                href={`/jobs/${job.id}`}
                className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
              >
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{job.title}</span>
                  <span className="block truncate text-muted-foreground">{job.company}</span>
                </div>
                <div className="flex w-16 shrink-0 justify-end">
                  <StaleBadge days={days} />
                </div>
                <div className="flex flex-col items-end gap-1">
                  <Badge variant="secondary" className="text-xs">
                    {STATUS_LABELS[job.status] ?? job.status}
                  </Badge>
                  <span className="text-xs text-muted-foreground">
                    {days === 0 ? "today" : `${days}d ago`}
                  </span>
                </div>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
            );
          })}
        </div>
      ) : (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No active applications yet.
        </p>
      )}
    </div>
  );
}

export function ActiveApplications({ jobs, byStatus }: { jobs: JobSummary[]; byStatus: Record<string, number> }) {
  const activeStatuses = new Set(["applied", "engaged", "offer_accepted", "offer_declined"]);
  const active = jobs.filter((j) => activeStatuses.has(j.status));
  const funnelTotal = Object.entries(byStatus).filter(([k]) => k !== "company_rejected" && k !== "withdrawn").reduce((sum, [, v]) => sum + v, 0);

  if (active.length === 0 && funnelTotal === 0) return null;

  return (
    <CollapsibleCard
      title="Active Applications"
      description="Applied jobs and post-ready pipeline"
      storageKey="dash-active-applications"
      action={
        <Link href="/jobs?status=applied,engaged,offer_accepted,offer_declined&clear_filters=1" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          View all
          <ArrowRight />
        </Link>
      }
    >
      <div className="grid gap-4 lg:grid-cols-[1.5fr_1fr]">
        <ActiveApplicationsContent jobs={jobs} />
        <div className="flex flex-col gap-3 border-l border-border pl-4">
          <h4 className="text-sm font-semibold text-muted-foreground">Pipeline</h4>
          <PipelineFunnel byStatus={byStatus} />
        </div>
      </div>
    </CollapsibleCard>
  );
}

export function Considering({ jobs }: { jobs: JobSummary[] }) {
  if (jobs.length === 0) return null;

  const sorted = [...jobs].sort((a, b) => (b.score ?? 0) - (a.score ?? 0));

  return (
    <CollapsibleCard
      title="Considering"
      description="Jobs in reviewing or interested — not yet applied"
      storageKey="dash-considering"
      action={
        <Link href="/jobs?status=reviewing,interested&clear_filters=1" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          View all
          <ArrowRight />
        </Link>
      }
    >
      <div className="flex flex-col divide-y divide-border">
          {sorted.map((job) => {
            const days = job.days_since_last_activity ?? 0;
            return (
              <Link
                key={job.id}
                href={`/jobs/${job.id}`}
                className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
              >
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{job.title}</span>
                  <span className="block truncate text-muted-foreground">{job.company}</span>
                </div>
                <div className="flex items-center gap-1.5">
                  {job.has_resume && (
                    <FileText className="size-3.5 text-primary" />
                  )}
                  {job.has_recruiter && (
                    <Users className="size-3.5 text-primary" />
                  )}
                </div>
                {job.score != null && (
                  <span className="w-10 shrink-0 text-right font-mono font-semibold">
                    {job.score}
                  </span>
                )}
                <Badge variant="secondary" className="text-xs">
                  {STATUS_LABELS[job.status] ?? job.status}
                </Badge>
                <span className="w-12 shrink-0 text-right text-xs text-muted-foreground">
                  {days === 0 ? "today" : `${days}d`}
                </span>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
            );
          })}
      </div>
    </CollapsibleCard>
  );
}

export function StaleAlerts({ jobs, threshold = 14 }: { jobs: JobSummary[]; threshold?: number }) {
  const stale = jobs
    .filter((j) => (j.days_since_last_activity ?? 0) >= threshold)
    .sort((a, b) => (b.days_since_last_activity ?? 0) - (a.days_since_last_activity ?? 0));

  if (stale.length === 0) return null;

  return (
    <CollapsibleCard
      title={
        <span className="flex items-center gap-2">
          <AlertTriangle className="size-5 text-amber-500" />
          Stale Alerts
        </span>
      }
      description={`No activity for ${threshold}+ days — may need follow-up`}
      storageKey="dash-stale-alerts"
      className="border-amber-500/30"
    >
      <div className="flex flex-col divide-y divide-border">
          {stale.map((job) => {
            const days = job.days_since_last_activity ?? 0;
            const isCritical = days >= threshold * 2;
            return (
              <Link
                key={job.id}
                href={`/jobs/${job.id}`}
                className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
              >
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{job.title}</span>
                  <span className="block truncate text-muted-foreground">{job.company}</span>
                </div>
                <span className={`w-10 shrink-0 text-right font-mono text-xs font-semibold ${isCritical ? "text-red-500" : "text-amber-500"}`}>
                  {days}d
                </span>
                <Badge variant="secondary" className="text-xs">
                  {STATUS_LABELS[job.status] ?? job.status}
                </Badge>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
            );
          })}
      </div>
    </CollapsibleCard>
  );
}
