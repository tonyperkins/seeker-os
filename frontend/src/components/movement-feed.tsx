"use client";

import Link from "next/link";
import {
  ArrowRight,
  CheckCircle2,
  Mail,
  MessageSquare,
  TrendingUp,
  XCircle,
  Ban,
  FileText,
} from "lucide-react";
import { CollapsibleCard } from "@/components/collapsible-card";
import { formatDateTime } from "@/lib/date";
import type { MovementEvent, MovementReport } from "@/lib/api";

const EVENT_META: Record<string, { label: string; icon: React.ComponentType<{ className?: string }>; color: string }> = {
  applied: { label: "Applied", icon: Mail, color: "text-violet-500" },
  engaged: { label: "Engaged", icon: MessageSquare, color: "text-sky-500" },
  company_rejected: { label: "Rejected", icon: XCircle, color: "text-destructive" },
  withdrawn: { label: "Withdrawn", icon: Ban, color: "text-muted-foreground" },
  offer_accepted: { label: "Offer Accepted", icon: CheckCircle2, color: "text-emerald-500" },
  offer_declined: { label: "Offer Declined", icon: XCircle, color: "text-amber-500" },
  skipped: { label: "Skipped", icon: Ban, color: "text-muted-foreground" },
  rejected: { label: "Rejected", icon: XCircle, color: "text-destructive" },
  overridden: { label: "Overridden", icon: TrendingUp, color: "text-amber-500" },
};

const REJECTION_LABELS: Record<string, string> = {
  rejected: "manual rejections",
  skipped: "skips",
  company_rejected: "company rejections",
};

const STATUS_LABELS: Record<string, string> = {
  discovered: "Discovered",
  filtered: "Filtered",
  jd_fetched: "JD Fetched",
  duplicate_flagged: "Duplicate",
  ready: "Ready",
  reviewing: "Reviewing",
  interested: "Interested",
  applied: "Applied",
  engaged: "Engaged",
  company_rejected: "Company Rejected",
  withdrawn: "Withdrawn",
  offer_accepted: "Offer Accepted",
  offer_declined: "Offer Declined",
  rejected: "Rejected",
  skipped: "Skipped",
  capped: "Capped",
  overridden: "Overridden",
};

function statusLabel(s: string | null | undefined): string {
  if (!s) return "—";
  return STATUS_LABELS[s] ?? s.replace(/_/g, " ");
}

export function MovementFeed({ events, rejectionCount, rejectionBreakdown }: {
  events: MovementEvent[];
  rejectionCount?: number;
  rejectionBreakdown?: Record<string, number>;
}) {
  return (
    <CollapsibleCard
      title="Movement"
      description="Recent status changes in the last 7 days"
      storageKey="dash-movement"
    >
      {/* Grouped rejection summary */}
      {rejectionCount != null && rejectionCount > 0 && (
        <div className="mb-2 flex items-center gap-2 rounded-md bg-muted/30 px-3 py-1.5 text-xs text-muted-foreground">
          <Ban className="size-3.5" />
          <span>
            {rejectionCount} rejection{rejectionCount !== 1 ? "s" : ""} this period
            {rejectionBreakdown && Object.keys(rejectionBreakdown).length > 0 && (
              <span className="text-muted-foreground/60">
                {" "}({Object.entries(rejectionBreakdown)
                  .map(([k, v]) => `${v} ${REJECTION_LABELS[k] ?? k}`)
                  .join(", ")})
              </span>
            )}
          </span>
        </div>
      )}

      {events.length === 0 && (rejectionCount == null || rejectionCount === 0) ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No status changes in the last 7 days.
        </p>
      ) : events.length === 0 ? (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No positive movement this period.
        </p>
      ) : (
        <div className="flex flex-col divide-y divide-border overflow-y-auto overflow-x-hidden max-h-72 min-h-0">
          {events.map((evt, i) => {
            const meta = EVENT_META[evt.event_type] ?? {
              label: evt.event_type,
              icon: FileText,
              color: "text-muted-foreground",
            };
            const Icon = meta.icon;
            return (
              <Link
                key={`${evt.job_id}-${evt.occurred_at}-${i}`}
                href={`/jobs/${evt.job_id}`}
                className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
              >
                <Icon className={`size-4 shrink-0 ${meta.color}`} />
                <div className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{evt.job_title}</span>
                  <span className="block truncate text-muted-foreground">{evt.company}</span>
                </div>
                <div className="flex flex-col items-end gap-0.5">
                  <span className="flex items-center gap-1 text-xs font-medium">
                    {evt.from_status && (
                      <>
                        <span className="text-muted-foreground/60">{statusLabel(evt.from_status)}</span>
                        <ArrowRight className="size-3 text-muted-foreground/40" />
                      </>
                    )}
                    <span className={meta.color}>{statusLabel(evt.to_status)}</span>
                  </span>
                  <span className="text-xs text-muted-foreground">
                    {formatDateTime(evt.occurred_at)}
                  </span>
                </div>
                <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
              </Link>
            );
          })}
        </div>
      )}
    </CollapsibleCard>
  );
}
