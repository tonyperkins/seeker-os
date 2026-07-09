"use client";

import { AlertTriangle, CheckCircle2, Mail, ShieldCheck, XCircle } from "lucide-react";
import { CollapsibleCard } from "@/components/collapsible-card";
import type { SignalQualityReport } from "@/lib/api";

const VERDICT_COLORS: Record<string, string> = {
  APPLY: "bg-emerald-500",
  CONDITIONAL: "bg-sky-500",
  MONITOR: "bg-amber-500",
  SKIP: "bg-red-500",
};

const VERDICT_LABELS: Record<string, string> = {
  APPLY: "Apply",
  CONDITIONAL: "Conditional",
  MONITOR: "Monitor",
  SKIP: "Skip",
};

export function SignalQualityCard({ report }: { report: SignalQualityReport | null }) {
  if (!report || report.total_analyzed === 0) {
    return (
      <CollapsibleCard
        title="Signal Quality"
        description="AI verdict distribution and calibration"
        storageKey="dash-signal-quality"
      >
        <p className="py-6 text-center text-sm text-muted-foreground">
          No AI analyses yet. Run the pipeline to generate verdicts.
        </p>
      </CollapsibleCard>
    );
  }

  return (
    <CollapsibleCard
      title="Signal Quality"
      description="AI verdict distribution and calibration"
      storageKey="dash-signal-quality"
      contentClassName="flex flex-col gap-4"
    >
      {/* Verdict distribution bars */}
      <div className="flex flex-col gap-2">
        {report.verdicts.map((v) => {
          const color = VERDICT_COLORS[v.verdict] ?? "bg-muted-foreground";
          const label = VERDICT_LABELS[v.verdict] ?? v.verdict;
          return (
            <div key={v.verdict} className="flex flex-col gap-1">
              <div className="flex items-baseline justify-between text-sm">
                <span className="text-muted-foreground">{label}</span>
                <span className="font-mono text-xs">
                  <span className="font-semibold text-foreground">{v.count}</span>
                  <span className="ml-1.5 text-muted-foreground">{v.pct}%</span>
                </span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className={`h-full rounded-full transition-all ${color}`}
                  style={{ width: `${Math.max(v.pct, 2)}%` }}
                />
              </div>
            </div>
          );
        })}
      </div>

      {/* Summary stats */}
      <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
        <div className="flex items-center gap-2">
          <CheckCircle2 className="size-4 text-emerald-500" />
          <div className="flex flex-col">
            <span className="text-xs text-muted-foreground">APPLY verdict share</span>
            <span className="font-mono text-sm font-semibold">{report.apply_rate}%</span>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <XCircle className="size-4 text-red-500" />
          <div className="flex flex-col">
            <span className="text-xs text-muted-foreground">SKIP verdict share</span>
            <span className="font-mono text-sm font-semibold">{report.skip_rate}%</span>
          </div>
        </div>
      </div>

      {/* APPLY → response rate (needs outcome data) */}
      <div className="grid grid-cols-1 gap-3 border-t border-border pt-3">
        <div className="flex items-center gap-2">
          <Mail className="size-4 text-violet-500" />
          <div className="flex flex-col">
            <span className="text-xs text-muted-foreground">APPLY → response rate</span>
            <span className="font-mono text-sm font-semibold">—</span>
            <span className="text-xs text-muted-foreground/60">needs outcome data</span>
          </div>
        </div>
      </div>

      {/* Calibration stats */}
      {report.calibration_available && (
        <div className="grid grid-cols-2 gap-3 border-t border-border pt-3">
          <div className="flex items-center gap-2">
            <AlertTriangle className="size-4 text-amber-500" />
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">False positive</span>
              <span className="font-mono text-sm font-semibold">{report.false_positive_pct}%</span>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <ShieldCheck className="size-4 text-sky-500" />
            <div className="flex flex-col">
              <span className="text-xs text-muted-foreground">False negative</span>
              <span className="font-mono text-sm font-semibold">{report.false_negative_pct}%</span>
            </div>
          </div>
        </div>
      )}

      <div className="border-t border-border pt-2 text-xs text-muted-foreground">
        {report.total_analyzed} jobs analyzed
      </div>
    </CollapsibleCard>
  );
}
