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

const TASK_PRIORITY: string[] = [
  "jd_analysis",
  "resume_generation_high_value",
  "resume_generation_standard",
  "manual",
];

function taskSortKey(task: string): number {
  const idx = TASK_PRIORITY.indexOf(task);
  return idx >= 0 ? idx : 99;
}

function splitModelId(provider: string, model: string): { prefix: string | null; base: string } {
  // Split the model id into upstream prefix and base name
  // e.g. "anthropic/claude-sonnet-4-6" → { prefix: "anthropic", base: "claude-sonnet-4-6" }
  // Only treat the prefix as an upstream qualifier if it differs from the provider id
  const slashIdx = model.indexOf("/");
  if (slashIdx >= 0) {
    const prefix = model.slice(0, slashIdx);
    const rest = model.slice(slashIdx + 1);
    if (prefix !== provider && !prefix.match(/^\d/)) {
      return { prefix, base: rest };
    }
  }
  return { prefix: null, base: model };
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
          As of {formatDate(report.pricing_fetched_at)}
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
      contentClassName="flex flex-col gap-3"
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

      {/* By task + By model side by side */}
      {(report.by_task.length > 0 || report.by_model.length > 0) && (
        <div className="grid grid-cols-1 lg:grid-cols-2 divide-y lg:divide-y-0 lg:divide-x divide-border border-t border-border pt-3">
          {/* By task breakdown */}
          {report.by_task.length > 0 && (
            <div className="flex flex-col gap-0.5 pr-4">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">By Task</h4>
              {(() => {
                const sorted = report.by_task.slice().sort((a, b) => {
                  const pa = taskSortKey(a.task);
                  const pb = taskSortKey(b.task);
                  if (pa !== pb) return pa - pb;
                  return b.estimated_cost - a.estimated_cost;
                });
                const maxCost = Math.max(...sorted.map((t) => t.estimated_cost), 0.001);
                return sorted.map((t) => {
                  const barPct = hasPricing ? Math.round((t.estimated_cost / maxCost) * 100) : 0;
                  return (
                    <div
                      key={t.task}
                      className="group relative rounded-sm px-2 py-1.5 transition-colors hover:bg-muted/40"
                    >
                      {hasPricing && barPct > 0 && (
                        <div
                          className="pointer-events-none absolute inset-y-0 left-0 rounded-sm bg-violet-500/8 transition-all"
                          style={{ width: `${barPct}%` }}
                        />
                      )}
                      <div className="relative grid grid-cols-[1fr_auto_auto] items-center gap-2 text-sm">
                        <span className="truncate text-sm text-foreground/80">
                          {TASK_LABELS[t.task] ?? t.task.replace(/_/g, " ")}
                        </span>
                        <span className="font-mono text-xs text-muted-foreground/60">
                          {t.calls}&thinsp;·&thinsp;{formatTokens(t.input_tokens + t.output_tokens)}
                        </span>
                        <span className="w-14 text-right font-mono text-xs font-semibold text-foreground">
                          {hasPricing ? formatCost(t.estimated_cost) : ""}
                        </span>
                      </div>
                    </div>
                  );
                });
              })()}
            </div>
          )}

          {/* By model breakdown — scrollable */}
          {report.by_model.length > 0 && (
            <div className="flex flex-col gap-0.5 min-h-0 pt-4 lg:pt-0 lg:pl-4">
              <h4 className="mb-2 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/60">By Model</h4>
              <div className="flex flex-col gap-0.5 overflow-y-auto max-h-52 min-h-0 pr-1">
                {report.by_model.map((m) => {
                  const noPricing = m.input_price_per_mtok == null && m.output_price_per_mtok == null;
                  const { prefix, base } = splitModelId(m.provider, m.model);
                  return (
                    <div
                      key={`${m.provider}/${m.model}`}
                      className="group grid grid-cols-[1fr_auto] items-start gap-3 rounded-sm px-2 py-1.5 transition-colors hover:bg-muted/40"
                    >
                      <div className="min-w-0 flex flex-col gap-0.5">
                        <span className="flex items-center gap-1">
                          {prefix && (
                            <span className="shrink-0 font-mono text-[11px] text-muted-foreground/50">
                              {prefix}/
                            </span>
                          )}
                          <span className="truncate text-sm text-foreground/80">
                            {base}
                          </span>
                          {m.pricing_source && (
                            <span className="shrink-0 rounded border border-border/60 bg-muted/40 px-1 py-0 font-mono text-[10px] text-muted-foreground/50">
                              {SOURCE_BADGE[m.pricing_source] ?? m.pricing_source}
                            </span>
                          )}
                        </span>
                        <span className="font-mono text-[11px] text-muted-foreground/50">
                          {m.provider}
                          {m.pricing_fetched_at && <span className="text-muted-foreground/50"> · {formatDate(m.pricing_fetched_at)}</span>}
                        </span>
                      </div>
                      <div className="flex flex-col items-end gap-0.5 pt-0.5">
                        {noPricing ? (
                          <span className="font-mono text-xs text-muted-foreground/50 italic">no pricing</span>
                        ) : (
                          <span className="font-mono text-sm font-semibold text-foreground">
                            {formatCost(m.estimated_cost)}
                          </span>
                        )}
                        <span className="font-mono text-[11px] text-muted-foreground/50">
                          {formatPrice(m.input_price_per_mtok)}/{formatPrice(m.output_price_per_mtok)}
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}
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
