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
  if (n === 0) return "$0";
  return `$${n.toFixed(2)}`;
}

const TASK_LABELS: Record<string, string> = {
  jd_analysis: "JD Analysis",
  resume_generation: "Resume Gen",
  resume_generation_high_value: "Resume Gen (High Value)",
  resume_generation_standard: "Resume Gen (Standard)",
  resume_parsing: "Resume Parsing",
  resume_validation: "Resume Validation",
  company_dossier_generation: "Company Dossier",
  cover_letter_generation: "Cover Letter",
  application_answer_generation: "Application Answers",
  application_answer_critique: "Answer Critique",
  accuracy_validation: "Accuracy Validation",
  onboarding_interview: "Onboarding Interview",
  metadata_extraction: "Metadata Extraction",
  manual: "Manual",
};

const SOURCE_BADGE: Record<string, string> = {
  yaml: "YAML",
  auto: "API",
  "yaml+auto": "YAML+API",
};

function shortenModel(provider: string, model: string): string {
  // Strip the provider namespace prefix from the model id if present
  // e.g. "anthropic/claude-sonnet-4-6" → "claude-sonnet-4-6"
  const slashIdx = model.indexOf("/");
  if (slashIdx >= 0) {
    const prefix = model.slice(0, slashIdx);
    const rest = model.slice(slashIdx + 1);
    // Only strip if the prefix looks like a provider namespace (not a version path segment)
    if (prefix !== provider && !prefix.match(/^\d/)) {
      return rest;
    }
  }
  return model;
}

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

  const hasPricing = report.pricing_configured;

  // Always-visible summary stats in the header action slot
  const headerStats = (
    <div className="flex flex-wrap items-center gap-x-5 gap-y-1 text-sm">
      <div className="flex items-center gap-1.5">
        <Cpu className="size-4 text-muted-foreground" />
        <span className="text-muted-foreground">Tokens</span>
        <span className="font-mono font-semibold text-foreground">
          {formatTokens(report.total_input_tokens + report.total_output_tokens)}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <DollarSign className="size-4 text-violet-500" />
        <span className="text-muted-foreground">Est. cost</span>
        <span className="font-mono font-semibold text-foreground">
          {hasPricing ? formatCost(report.total_estimated_cost) : "—"}
        </span>
      </div>
      <div className="flex items-center gap-1.5">
        <TrendingDown className="size-4 text-sky-500" />
        <span className="text-muted-foreground">Per applied</span>
        <span className="font-mono font-semibold text-foreground">
          {report.cost_per_applied != null ? `$${report.cost_per_applied.toFixed(2)}` : "—"}
        </span>
      </div>
      {hasPricing && report.pricing_fetched_at && (
        <span className={`font-mono ${report.pricing_stale ? "text-amber-600 dark:text-amber-500" : "text-muted-foreground"}`}>
          Pricing as of {formatDate(report.pricing_fetched_at)}
          {report.pricing_stale && ` · stale`}
        </span>
      )}
    </div>
  );

  return (
    <CollapsibleCard
      title="LLM Spend"
      description="Token usage and estimated cost"
      storageKey="dash-spend"
      action={headerStats}
      contentClassName="flex flex-col gap-4"
    >
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
        <div className="flex flex-col gap-1.5 border-t border-border pt-3">
          <h4 className="text-xs font-semibold text-muted-foreground">By Task</h4>
          {report.by_task.map((t) => (
            <div key={t.task} className="grid grid-cols-[1fr_auto_auto] items-baseline gap-3 text-sm">
              <span className="truncate text-muted-foreground">
                {TASK_LABELS[t.task] ?? t.task.replace(/_/g, " ")}
              </span>
              <span className="text-right font-mono text-xs text-muted-foreground/70">
                {t.calls} · {formatTokens(t.input_tokens + t.output_tokens)}
              </span>
              <span className="w-16 text-right font-mono text-xs font-semibold text-foreground">
                {hasPricing ? formatCost(t.estimated_cost) : ""}
              </span>
            </div>
          ))}
        </div>
      )}

      {/* By model breakdown */}
      {report.by_model.length > 0 && (
        <div className="flex flex-col gap-1.5 border-t border-border pt-3">
          <h4 className="text-xs font-semibold text-muted-foreground">By Model</h4>
          {report.by_model.map((m) => {
            const noPricing = m.input_price_per_mtok == null && m.output_price_per_mtok == null;
            return (
              <div key={`${m.provider}/${m.model}`} className="grid grid-cols-[1fr_auto] items-baseline gap-3 text-sm">
                <div className="min-w-0 flex flex-col gap-0.5">
                  <span className="flex items-center gap-1.5">
                    <span className="truncate text-muted-foreground">
                      {shortenModel(m.provider, m.model)}
                    </span>
                    {m.pricing_source && (
                      <span className="shrink-0 rounded bg-muted/50 px-1 py-0 text-[10px] font-medium text-muted-foreground/60">
                        {SOURCE_BADGE[m.pricing_source] ?? m.pricing_source}
                      </span>
                    )}
                  </span>
                  <span className="text-xs text-muted-foreground/50">
                    {m.provider}
                    {m.pricing_fetched_at && ` · ${formatDate(m.pricing_fetched_at)}`}
                  </span>
                </div>
                <div className="flex flex-col items-end gap-0.5">
                  <span className={`font-mono text-xs font-semibold ${noPricing ? "text-muted-foreground/40" : "text-foreground"}`}>
                    {noPricing ? "no pricing" : formatCost(m.estimated_cost)}
                  </span>
                  <span className="font-mono text-xs text-muted-foreground/60">
                    {formatPrice(m.input_price_per_mtok)} / {formatPrice(m.output_price_per_mtok)}
                  </span>
                </div>
              </div>
            );
          })}
        </div>
      )}

      {!hasPricing && (
        <div className="border-t border-border pt-2 text-xs text-muted-foreground">
          Add <code className="font-mono">input_price_per_mtok</code> / <code className="font-mono">output_price_per_mtok</code> to models in providers.yml for cost estimates
        </div>
      )}
    </CollapsibleCard>
  );
}
