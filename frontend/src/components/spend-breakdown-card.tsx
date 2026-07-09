"use client";

import { DollarSign, Cpu, TrendingDown, AlertTriangle } from "lucide-react";
import { CollapsibleCard } from "@/components/collapsible-card";
import { formatDate } from "@/lib/date";
import type { SpendReport } from "@/lib/api";

function formatTokens(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function formatCost(n: number): string {
  if (n === 0) return "$0.00";
  if (n < 0.01) return "<$0.01";
  return `$${n.toFixed(2)}`;
}

function formatPrice(n: number | null): string {
  if (n === null) return "—";
  if (n === 0) return "$0.00";
  return `$${n.toFixed(2)}`;
}

const TASK_LABELS: Record<string, string> = {
  jd_analysis: "JD Analysis",
  resume_generation: "Resume Gen",
  company_dossier_generation: "Company Dossier",
  resume_validation: "Resume Validation",
};

const SOURCE_LABELS: Record<string, string> = {
  yaml: "YAML",
  auto: "API",
  "yaml+auto": "YAML+API",
};

export function SpendBreakdownCard({ report }: { report: SpendReport | null }) {
  if (!report || report.total_calls === 0) {
    return (
      <CollapsibleCard
        title="LLM Spend"
        description="Token usage and estimated cost"
        storageKey="dash-spend"
      >
        <p className="py-6 text-center text-sm text-muted-foreground">
          No LLM calls yet. Run the pipeline to generate data.
        </p>
      </CollapsibleCard>
    );
  }

  return (
    <CollapsibleCard
      title="LLM Spend"
      description="Token usage and estimated cost"
      storageKey="dash-spend"
      contentClassName="flex flex-col gap-4"
    >
      {/* Summary stats */}
      <div className="grid grid-cols-3 gap-3">
        <div className="flex items-center gap-2">
          <Cpu className="size-4 text-muted-foreground" />
          <div className="flex flex-col">
            <span className="text-xs text-muted-foreground">Tokens</span>
            <span className="font-mono text-sm font-semibold">
              {formatTokens(report.total_input_tokens + report.total_output_tokens)}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <DollarSign className="size-4 text-violet-500" />
          <div className="flex flex-col">
            <span className="text-xs text-muted-foreground">Est. cost</span>
            <span className="font-mono text-sm font-semibold">
              {report.pricing_configured ? formatCost(report.total_estimated_cost) : "—"}
            </span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <TrendingDown className="size-4 text-sky-500" />
          <div className="flex flex-col">
            <span className="text-xs text-muted-foreground">Per applied</span>
            <span className="font-mono text-sm font-semibold">
              {report.cost_per_applied != null ? `$${report.cost_per_applied.toFixed(2)}` : "—"}
            </span>
          </div>
        </div>
      </div>

      {/* Pricing freshness line */}
      {report.pricing_configured && report.pricing_fetched_at && (
        <div className={`text-xs ${report.pricing_stale ? "text-amber-600 dark:text-amber-500" : "text-muted-foreground"}`}>
          Pricing as of {formatDate(report.pricing_fetched_at)}
          {report.pricing_stale && ` · stale (>${report.pricing_stale_after_days}d)`}
        </div>
      )}

      {/* Route price warnings */}
      {report.route_pricing.length > 0 && (
        <div className="flex flex-col gap-1.5 border-t border-border pt-3">
          {report.route_pricing.map((rp) => (
            <div key={rp.model} className="flex items-center gap-2 text-xs text-amber-600 dark:text-amber-500">
              <AlertTriangle className="size-3.5 shrink-0" />
              <span className="font-medium">{rp.model}</span>
              <span className="text-muted-foreground">
                {rp.variance_pct}% variance across {rp.routes.length} routes
              </span>
            </div>
          ))}
        </div>
      )}

      {/* By task breakdown */}
      {report.by_task.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <h4 className="text-xs font-semibold text-muted-foreground">By Task</h4>
          {report.by_task.map((t) => (
            <div key={t.task} className="flex items-baseline justify-between text-sm">
              <span className="text-muted-foreground">
                {TASK_LABELS[t.task] ?? t.task}
              </span>
              <span className="font-mono text-xs">
                <span className="text-muted-foreground">{t.calls} calls · {formatTokens(t.input_tokens + t.output_tokens)}</span>
                {report.pricing_configured && (
                  <span className="ml-2 font-semibold text-foreground">{formatCost(t.estimated_cost)}</span>
                )}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* By model breakdown */}
      {report.pricing_configured && report.by_model.length > 0 && (
        <div className="flex flex-col gap-2 border-t border-border pt-3">
          <h4 className="text-xs font-semibold text-muted-foreground">By Model</h4>
          {report.by_model.map((m) => (
            <div key={`${m.provider}/${m.model}`} className="flex items-baseline justify-between text-sm">
              <div className="min-w-0 flex-1">
                <span className="block truncate text-muted-foreground">
                  {m.provider}/{m.model}
                </span>
                {m.pricing_source && (
                  <span className="text-xs text-muted-foreground/60">
                    {SOURCE_LABELS[m.pricing_source] ?? m.pricing_source}
                    {m.pricing_fetched_at && ` · ${formatDate(m.pricing_fetched_at)}`}
                  </span>
                )}
              </div>
              <span className="font-mono text-xs">
                <span className="text-muted-foreground">
                  {formatPrice(m.input_price_per_mtok)}/{formatPrice(m.output_price_per_mtok)}
                </span>
                <span className="ml-2 font-semibold text-foreground">{formatCost(m.estimated_cost)}</span>
              </span>
            </div>
          ))}
        </div>
      )}

      {!report.pricing_configured && (
        <div className="border-t border-border pt-2 text-xs text-muted-foreground">
          Add <code className="font-mono">input_price_per_mtok</code> / <code className="font-mono">output_price_per_mtok</code> to models in providers.yml for cost estimates
        </div>
      )}
    </CollapsibleCard>
  );
}
