"use client";

import { useState, useEffect, useCallback } from "react";
import {
  Brain,
  Loader2,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  XCircle,
  AlertTriangle,
  Eye,
  TrendingUp,
  TrendingDown,
  Target,
  Lightbulb,
  Flag,
  Cpu,
  Copy,
  Check,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { api, type JobAnalysisResult, type NamedGap } from "@/lib/api";
import { ErrorBanner } from "@/components/error-banner";

const VERDICT_STYLES: Record<string, { color: string; label: string }> = {
  APPLY: { color: "text-emerald-600", label: "APPLY" },
  CONDITIONAL: { color: "text-blue-600", label: "CONDITIONAL" },
  MONITOR: { color: "text-amber-600", label: "MONITOR" },
  SKIP: { color: "text-destructive", label: "SKIP" },
};

const SEVERITY_ICONS: Record<string, typeof CheckCircle2> = {
  low: CheckCircle2,
  med: AlertTriangle,
  high: XCircle,
  blocker: Flag,
};

const SEVERITY_COLORS: Record<string, string> = {
  low: "text-muted-foreground",
  med: "text-amber-600",
  high: "text-destructive",
  blocker: "text-destructive font-semibold",
};

function formatAnalysisText(a: JobAnalysisResult): string {
  const lines: string[] = [];
  lines.push(`Verdict: ${a.verdict}`);
  lines.push(`Score: ${a.weighted_score.toFixed(1)}`);
  lines.push(`Confidence: ${Math.round(a.confidence * 100)}%`);
  lines.push(`Summary: ${a.one_line}`);
  if (a.hard_blockers.length > 0) {
    lines.push("\nHard Blockers:");
    a.hard_blockers.forEach(b => lines.push(`  - ${b.type}: ${b.detail}`));
  }
  if (a.named_gaps.length > 0) {
    lines.push("\nNamed Gaps:");
    a.named_gaps.forEach(g => lines.push(`  - ${g.area} (${g.severity}): JD requires ${g.jd_requires}, actual ${g.candidate_actual}`));
  }
  if (a.rubric_breakdown.length > 0) {
    lines.push("\nRubric Breakdown:");
    a.rubric_breakdown.forEach(d => lines.push(`  - ${d.dimension}: ${d.weighted.toFixed(1)} (${d.raw.toFixed(1)} × ${d.weight.toFixed(1)})${d.note ? ` — ${d.note}` : ""}`));
  }
  if (a.bonuses_applied.length > 0) lines.push(`\nBonuses: ${a.bonuses_applied.join(", ")}`);
  if (a.penalties_applied.length > 0) lines.push(`Penalties: ${a.penalties_applied.join(", ")}`);
  if (a.comp.note) lines.push(`\nCompensation: ${a.comp.note}`);
  if (a.positioning.note) lines.push(`Positioning: ${a.positioning.note}`);
  if (a.company_fit.note) lines.push(`Company Fit: ${a.company_fit.note}`);
  if (a.tailoring.lead_with.length > 0) lines.push(`\nLead with: ${a.tailoring.lead_with.join(", ")}`);
  if (a.tailoring.reframe_summary) lines.push(`Reframe: ${a.tailoring.reframe_summary}`);
  if (a.tailoring.do_not_claim.length > 0) lines.push(`Do NOT claim: ${a.tailoring.do_not_claim.join(", ")}`);
  if (a.red_flags.length > 0) {
    lines.push("\nRed Flags:");
    a.red_flags.forEach(f => lines.push(`  - ${f}`));
  }
  return lines.join("\n");
}

function CopyButtonFromData({ data }: { data: JobAnalysisResult }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(formatAnalysisText(data)).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        });
      }}
    >
      {copied ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
    </Button>
  );
}

export function JobAnalysis({ jobId }: { jobId: number }) {
  const [data, setData] = useState<JobAnalysisResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  async function loadAnalysis() {
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const result = await api.jobs.analysis.get(jobId);
      setData(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      if (msg.includes("404") || msg.includes("No analysis")) {
        setNotFound(true);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }

  const runAnalysis = useCallback(async () => {
    setRunning(true);
    setError(null);
    setNotFound(false);
    try {
      const result = await api.jobs.analysis.run(jobId);
      setData(result);
      setNotFound(false);
      window.dispatchEvent(new Event("analysis-complete"));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setRunning(false);
    }
  }, [jobId]);

  useEffect(() => {
    loadAnalysis();
  }, [jobId]);

  useEffect(() => {
    function onRunAll() {
      runAnalysis();
    }
    window.addEventListener("run-all-triggered", onRunAll);
    return () => window.removeEventListener("run-all-triggered", onRunAll);
  }, [runAnalysis]);

  const verdictStyle = data ? VERDICT_STYLES[data.verdict] || VERDICT_STYLES.SKIP : null;

  return (
    <CollapsibleCard
      title="AI Analysis"
      icon={Brain}
      description={
        data
          ? `Analyzed ${new Date(data.analyzed_at).toLocaleDateString()}`
          : "JD fit analysis against your profile"
      }
      action={
        <div className="flex items-center gap-1">
          {data && (
            <CopyButtonFromData data={data} />
          )}
          <Button
            variant="outline"
            size="sm"
            disabled={running}
            onClick={runAnalysis}
          >
            {running ? (
              <Loader2 className="animate-spin" />
            ) : (
              <RefreshCw />
            )}
            {data ? "Refresh" : "Analyze"}
          </Button>
        </div>
      }
    >
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading analysis…
          </div>
        )}

        {error && (
          <ErrorBanner message={error} />
        )}

        {notFound && !loading && !running && (
          <div className="flex flex-col gap-2 text-sm text-muted-foreground">
            <p>No analysis yet. Click &ldquo;Analyze&rdquo; to evaluate this job against your profile.</p>
          </div>
        )}

        {running && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Analyzing job fit… This may take a few seconds.
          </div>
        )}

        {data && !running && (
          <>
            {/* Verdict + one-liner */}
            <div className="flex flex-col gap-2">
              <div className="flex items-center gap-2">
                {verdictStyle && (
                  <Badge variant="outline" className={`text-sm font-semibold ${verdictStyle.color}`}>
                    {verdictStyle.label}
                  </Badge>
                )}
                <Badge variant="secondary" className="text-sm">
                  Score: {data.weighted_score.toFixed(1)}
                </Badge>
                <Badge variant="outline" className="text-xs">
                  {Math.round(data.confidence * 100)}% confidence
                </Badge>
              </div>
              <p className="text-sm leading-relaxed">{data.one_line}</p>
            </div>

            {/* Hard blockers */}
            {data.hard_blockers.length > 0 && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium text-destructive">
                  <Flag className="size-4" />
                  Hard Blockers
                </div>
                {data.hard_blockers.map((blocker, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-destructive">
                    <XCircle className="mt-0.5 size-3 shrink-0" />
                    <div>
                      <span className="font-medium">{blocker.type}</span>
                      <p className="text-muted-foreground">{blocker.detail}</p>
                    </div>
                  </div>
                ))}
              </div>
            )}

            {/* Named gaps */}
            {data.named_gaps.length > 0 && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Target className="size-4 text-muted-foreground" />
                  Named Gaps
                </div>
                {data.named_gaps.map((gap: NamedGap, i) => {
                  const GapIcon = SEVERITY_ICONS[gap.severity] || AlertCircle;
                  return (
                    <div key={i} className="flex items-start gap-2 text-xs">
                      <GapIcon className={`mt-0.5 size-3 shrink-0 ${SEVERITY_COLORS[gap.severity] || ""}`} />
                      <div className="flex flex-col gap-0.5">
                        <span className="font-medium">{gap.area}</span>
                        <span className="text-muted-foreground">
                          <span className="font-normal">JD requires:</span> {gap.jd_requires}
                        </span>
                        <span className="text-muted-foreground">
                          <span className="font-normal">Candidate actual:</span> {gap.candidate_actual}
                        </span>
                        <Badge variant="outline" className="mt-0.5 w-fit text-xs">
                          {gap.severity}
                        </Badge>
                      </div>
                    </div>
                  );
                })}
              </div>
            )}

            {/* Rubric breakdown */}
            {data.rubric_breakdown.length > 0 && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Cpu className="size-4 text-muted-foreground" />
                  Rubric Breakdown
                </div>
                {data.rubric_breakdown.map((dim, i) => (
                  <div key={i} className="flex flex-col gap-0.5 text-xs">
                    <div className="flex items-center justify-between">
                      <span className="font-medium">{dim.dimension}</span>
                      <span className="text-muted-foreground">
                        {dim.weighted.toFixed(1)} <span className="text-muted-foreground/60">({dim.raw.toFixed(1)} × {dim.weight.toFixed(1)})</span>
                      </span>
                    </div>
                    {dim.note && <span className="text-muted-foreground">{dim.note}</span>}
                  </div>
                ))}
              </div>
            )}

            {/* Bonuses & penalties */}
            {(data.bonuses_applied.length > 0 || data.penalties_applied.length > 0) && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-3">
                {data.bonuses_applied.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {data.bonuses_applied.map((bonus, i) => (
                      <Badge key={i} variant="outline" className="text-xs text-emerald-600">
                        <TrendingUp className="mr-1 size-3" />
                        {bonus}
                      </Badge>
                    ))}
                  </div>
                )}
                {data.penalties_applied.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {data.penalties_applied.map((penalty, i) => (
                      <Badge key={i} variant="outline" className="text-xs text-destructive">
                        <TrendingDown className="mr-1 size-3" />
                        {penalty}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Comp assessment */}
            {data.comp.note && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Target className="size-4 text-muted-foreground" />
                  Compensation
                </div>
                <div className="flex items-center gap-2 text-xs">
                  {data.comp.meets_floor === true && (
                    <Badge variant="outline" className="text-xs text-emerald-600">
                      <CheckCircle2 className="mr-1 size-3" />
                      Meets floor
                    </Badge>
                  )}
                  {data.comp.meets_floor === false && (
                    <Badge variant="outline" className="text-xs text-destructive">
                      <XCircle className="mr-1 size-3" />
                      Below floor
                    </Badge>
                  )}
                  {data.comp.meets_floor === null && (
                    <Badge variant="outline" className="text-xs text-amber-600">
                      <AlertTriangle className="mr-1 size-3" />
                      Comp unposted
                    </Badge>
                  )}
                  <span className="text-muted-foreground">{data.comp.note}</span>
                </div>
              </div>
            )}

            {/* Positioning */}
            {data.positioning.note && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Eye className="size-4 text-muted-foreground" />
                  Positioning
                </div>
                <div className="flex items-center gap-2 text-xs">
                  {data.positioning.aligned ? (
                    <Badge variant="outline" className="text-xs text-emerald-600">
                      <CheckCircle2 className="mr-1 size-3" />
                      Aligned
                    </Badge>
                  ) : (
                    <Badge variant="outline" className="text-xs text-destructive">
                      <XCircle className="mr-1 size-3" />
                      Mismatch
                    </Badge>
                  )}
                  <span className="text-muted-foreground">{data.positioning.note}</span>
                </div>
              </div>
            )}

            {/* Company fit */}
            {data.company_fit.note && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Target className="size-4 text-muted-foreground" />
                  Company Fit
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs">
                  {data.company_fit.size_bucket && (
                    <div>
                      <span className="text-muted-foreground">Size: </span>
                      <span className="font-medium">{data.company_fit.size_bucket}</span>
                    </div>
                  )}
                  {data.company_fit.stage && (
                    <div>
                      <span className="text-muted-foreground">Stage: </span>
                      <span className="font-medium">{data.company_fit.stage}</span>
                    </div>
                  )}
                  {data.company_fit.remote_policy && (
                    <div>
                      <span className="text-muted-foreground">Remote: </span>
                      <span className="font-medium capitalize">{data.company_fit.remote_policy}</span>
                    </div>
                  )}
                </div>
                {data.company_fit.note && (
                  <p className="text-xs text-muted-foreground">{data.company_fit.note}</p>
                )}
              </div>
            )}

            {/* Tailoring guidance */}
            {(data.tailoring.lead_with.length > 0 || data.tailoring.reframe_summary || data.tailoring.do_not_claim.length > 0) && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Lightbulb className="size-4 text-muted-foreground" />
                  Tailoring Guidance
                </div>
                {data.tailoring.lead_with.length > 0 && (
                  <div className="flex flex-col gap-0.5 text-xs">
                    <span className="text-muted-foreground font-medium">Lead with:</span>
                    <div className="flex flex-wrap gap-1.5">
                      {data.tailoring.lead_with.map((item, i) => (
                        <Badge key={i} variant="secondary" className="text-xs">
                          {item}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
                {data.tailoring.reframe_summary && (
                  <p className="text-xs text-muted-foreground">{data.tailoring.reframe_summary}</p>
                )}
                {data.tailoring.do_not_claim.length > 0 && (
                  <div className="flex flex-col gap-0.5 text-xs">
                    <span className="text-destructive font-medium">Do NOT claim:</span>
                    <div className="flex flex-wrap gap-1.5">
                      {data.tailoring.do_not_claim.map((item, i) => (
                        <Badge key={i} variant="outline" className="text-xs text-destructive">
                          {item}
                        </Badge>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            )}

            {/* Red flags */}
            {data.red_flags.length > 0 && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium text-destructive">
                  <AlertTriangle className="size-4" />
                  Red Flags
                </div>
                {data.red_flags.map((flag, i) => (
                  <div key={i} className="flex items-start gap-2 text-xs text-destructive">
                    <AlertTriangle className="mt-0.5 size-3 shrink-0" />
                    {flag}
                  </div>
                ))}
              </div>
            )}

            {/* LLM metadata */}
            <Separator />
            <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
              <Badge variant="outline" className="text-xs">
                {data.provider} / {data.model}
              </Badge>
              <span>{data.input_tokens + data.output_tokens} tokens</span>
              <span>· {(data.latency_ms / 1000).toFixed(1)}s</span>
            </div>
          </>
        )}
    </CollapsibleCard>
  );
}
