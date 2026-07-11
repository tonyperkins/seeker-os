import Link from "next/link";
import { ClipboardCheck, FileText, Mail, DollarSign } from "lucide-react";
import { formatCurrency } from "@/lib/format";

interface MetricCardProps {
  label: string;
  value: number | string;
  href?: string;
  icon: React.ComponentType<{ className?: string }>;
  accent?: string;
  sublabel?: string;
}

function MetricCard({ label, value, href, icon: Icon, accent, sublabel }: MetricCardProps) {
  const content = (
    <div className="flex items-center gap-3 rounded-lg border bg-card px-4 py-3 transition-colors hover:bg-muted/30">
      <Icon className={`size-5 shrink-0 ${accent ?? "text-muted-foreground"}`} />
      <div className="min-w-0 flex-1">
        <div className="text-xs text-muted-foreground">{label}</div>
        <div className="font-mono text-lg font-semibold leading-tight">{value}</div>
        {sublabel && (
          <div className="truncate text-xs text-muted-foreground">{sublabel}</div>
        )}
      </div>
    </div>
  );

  if (href) {
    return <Link href={href}>{content}</Link>;
  }
  return content;
}

export interface MetricCardsData {
  needsDecision: number;
  docsToReview: number;
  awaitingReply: number;
  costPerReady: number | null;
  pricingConfigured: boolean;
}

export function MetricCards({ data }: { data: MetricCardsData }) {
  const costLabel = data.costPerReady != null
    ? formatCurrency(data.costPerReady)
    : data.pricingConfigured
      ? "$0.00"
      : "—";
  const costSub = data.pricingConfigured
    ? "per ready job"
    : "add pricing to providers.yml";

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
      <MetricCard
        label="Needs Decision"
        value={data.needsDecision}
        href="/jobs?status=ready"
        icon={ClipboardCheck}
        accent="text-emerald-500"
        sublabel="ready jobs"
      />
      <MetricCard
        label="Docs to Review"
        value={data.docsToReview}
        href="/resumes"
        icon={FileText}
        accent="text-amber-500"
        sublabel={data.docsToReview > 0 ? "pending validation" : undefined}
      />
      <MetricCard
        label="Awaiting Reply"
        value={data.awaitingReply}
        href="/jobs?status=applied,engaged"
        icon={Mail}
        accent="text-sky-500"
        sublabel="applied / engaged"
      />
      <MetricCard
        label="Cost per Ready"
        value={costLabel}
        icon={DollarSign}
        accent={data.pricingConfigured ? "text-violet-500" : "text-muted-foreground/50"}
        sublabel={costSub}
      />
    </div>
  );
}
