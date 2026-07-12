"use client";

import { useState, useEffect, useRef, useCallback } from "react";
import {
  Building2,
  Loader2,
  Globe,
  TrendingUp,
  Users,
  ExternalLink,
  RefreshCw,
  AlertCircle,
  CheckCircle2,
  XCircle,
  Eye,
  Briefcase,
  MapPin,
  Heart,
  ShieldAlert,
  Search,
  Database,
  Sparkles,
  CheckCircle,
  Copy,
  Check,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { api, type CompanyResearchResult } from "@/lib/api";
import { ErrorBanner } from "@/components/error-banner";

function ConfidenceBadge({ confidence }: { confidence: number }) {
  const pct = Math.round(confidence * 100);
  const color =
    confidence >= 0.7
      ? "text-emerald-600"
      : confidence >= 0.4
        ? "text-amber-600"
        : "text-destructive";
  return (
    <Badge variant="outline" className={`text-xs ${color}`}>
      {pct}% confidence
    </Badge>
  );
}

function StrippedBadge({ count }: { count: number }) {
  if (count <= 0) return null;
  return (
    <Badge variant="outline" className="text-xs text-amber-600">
      <ShieldAlert className="size-3 mr-1" />
      {count} source{count > 1 ? "s" : ""} stripped
    </Badge>
  );
}

function VerdictFlagRow({
  items,
  icon: Icon,
  color,
}: {
  items: string[];
  icon: typeof CheckCircle2;
  color: string;
}) {
  if (items.length === 0) return null;
  return (
    <div className="flex flex-wrap gap-1.5">
      {items.map((item, i) => (
        <Badge key={i} variant="outline" className={`text-xs ${color}`}>
          <Icon className="size-3 mr-1" />
          {item}
        </Badge>
      ))}
    </div>
  );
}

const RESEARCH_STEPS = [
  { icon: Search, label: "Searching Wikipedia", duration: 2000 },
  { icon: Database, label: "Querying Wikidata", duration: 2000 },
  { icon: Globe, label: "Searching the web", duration: 3000 },
  { icon: Sparkles, label: "Generating AI dossier", duration: 8000 },
  { icon: CheckCircle, label: "Finalizing results", duration: 1000 },
] as const;

function ResearchProgress({ done }: { done: boolean }) {
  const [currentStep, setCurrentStep] = useState(0);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    if (done) {
      if (timerRef.current) clearTimeout(timerRef.current);
      // Completion is an external workflow transition reflected in progress state.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setCurrentStep(RESEARCH_STEPS.length);
      return;
    }

    if (currentStep >= RESEARCH_STEPS.length - 1) return;

    timerRef.current = setTimeout(() => {
      setCurrentStep((s) => Math.min(s + 1, RESEARCH_STEPS.length - 1));
    }, RESEARCH_STEPS[currentStep].duration);

    return () => {
      if (timerRef.current) clearTimeout(timerRef.current);
    };
  }, [currentStep, done]);

  return (
    <div className="flex flex-col gap-2 py-1">
      {RESEARCH_STEPS.map((step, i) => {
        const isDone = done || i < currentStep;
        const isActive = !done && i === currentStep;
        const isPending = !done && i > currentStep;
        const StepIcon = step.icon;

        return (
          <div
            key={i}
            className={`flex items-center gap-2.5 text-sm transition-colors duration-300 ${
              isPending ? "text-muted-foreground/50" : "text-foreground"
            }`}
          >
            <div className="flex size-5 items-center justify-center shrink-0">
              {isDone ? (
                <CheckCircle2 className="size-4 text-emerald-600" />
              ) : isActive ? (
                <Loader2 className="size-4 animate-spin text-primary" />
              ) : (
                <StepIcon className="size-4" />
              )}
            </div>
            <span className={isPending ? "" : isDone ? "text-emerald-600" : "font-medium"}>
              {step.label}
              {isActive && <span className="text-muted-foreground font-normal">…</span>}
            </span>
          </div>
        );
      })}
    </div>
  );
}

function formatResearchText(r: CompanyResearchResult): string {
  const lines: string[] = [];
  if (r.summary) {
    lines.push(r.summary);
    lines.push(`Confidence: ${Math.round(r.overall_confidence * 100)}%`);
  }
  if (r.wikipedia) {
    lines.push(`\nAbout: ${r.wikipedia.extract}`);
  }
  if (r.funding) {
    lines.push("\nFunding & Stage:");
    if (r.funding.stage) lines.push(`  Stage: ${r.funding.stage}`);
    if (r.funding.public) lines.push(`  Public: Yes`);
    if (r.funding.founded) lines.push(`  Founded: ${r.funding.founded}`);
    if (r.funding.hq) lines.push(`  HQ: ${r.funding.hq}`);
    if (r.funding.total_raised_usd != null) lines.push(`  Total raised: $${(r.funding.total_raised_usd / 1e6).toFixed(0)}M`);
    if (r.funding.valuation_usd != null) lines.push(`  Valuation: $${(r.funding.valuation_usd / 1e6).toFixed(0)}M`);
    if (r.funding.headcount != null) lines.push(`  Headcount: ${r.funding.headcount.toLocaleString()}`);
    if (r.funding.headcount_trend) lines.push(`  Trend: ${r.funding.headcount_trend}`);
    if (r.funding.financial_health) lines.push(`  Health: ${r.funding.financial_health}`);
    if (r.funding.layoffs.length > 0) {
      lines.push("  Layoffs:");
      r.funding.layoffs.forEach(l => {
        let s = `    ${l.date || ""}`;
        if (l.pct != null) s += ` (${l.pct}%)`;
        if (l.count != null) s += ` · ${l.count} employees`;
        lines.push(s);
      });
    }
  }
  if (r.sentiment) {
    lines.push("\nEmployee Sentiment:");
    if (r.sentiment.overall_rating_estimate != null) lines.push(`  Rating: ${r.sentiment.overall_rating_estimate.toFixed(1)} / ${r.sentiment.rating_scale}`);
    if (r.sentiment.ceo_approval_pct != null) lines.push(`  CEO approval: ${r.sentiment.ceo_approval_pct.toFixed(0)}%`);
    if (r.sentiment.recommend_pct != null) lines.push(`  Recommend: ${r.sentiment.recommend_pct.toFixed(0)}%`);
    if (r.sentiment.positives.length > 0) {
      lines.push("  Positives:");
      r.sentiment.positives.forEach(t => lines.push(`    + ${t.theme} (${t.frequency})${t.paraphrase ? `: ${t.paraphrase}` : ""}`));
    }
    if (r.sentiment.negatives.length > 0) {
      lines.push("  Negatives:");
      r.sentiment.negatives.forEach(t => lines.push(`    - ${t.theme} (${t.frequency})${t.paraphrase ? `: ${t.paraphrase}` : ""}`));
    }
  }
  if (r.fit) {
    lines.push("\nFit Signals:");
    if (r.fit.remote_policy) lines.push(`  Remote: ${r.fit.remote_policy}`);
    if (r.fit.size_bucket) lines.push(`  Size: ${r.fit.size_bucket}`);
    if (r.fit.ic_vs_mgmt_culture) lines.push(`  Culture: ${r.fit.ic_vs_mgmt_culture}`);
    if (r.fit.comp_band) lines.push(`  Comp: ${r.fit.comp_band}`);
    if (r.fit.remote_walkback) lines.push(`  Walkback: ${r.fit.remote_walkback}`);
  }
  if (r.verdict_flags.green.length > 0) lines.push(`\nGreen flags: ${r.verdict_flags.green.join(", ")}`);
  if (r.verdict_flags.red.length > 0) lines.push(`Red flags: ${r.verdict_flags.red.join(", ")}`);
  if (r.verdict_flags.watch.length > 0) lines.push(`Watch: ${r.verdict_flags.watch.join(", ")}`);
  return lines.join("\n");
}

function CopyResearchButton({ data }: { data: CompanyResearchResult }) {
  const [copied, setCopied] = useState(false);
  return (
    <Button
      variant="ghost"
      size="sm"
      onClick={(e) => {
        e.stopPropagation();
        navigator.clipboard.writeText(formatResearchText(data)).then(() => {
          setCopied(true);
          setTimeout(() => setCopied(false), 2000);
        });
      }}
    >
      {copied ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
    </Button>
  );
}

export function CompanyResearch({ jobId }: { jobId: number }) {
  const [data, setData] = useState<CompanyResearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [researchDone, setResearchDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  const loadResearch = useCallback(async () => {
    setLoading(true);
    setError(null);
    setNotFound(false);
    try {
      const result = await api.jobs.companyResearch.get(jobId);
      setData(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Failed to load";
      if (msg.includes("404") || msg.includes("No company research")) {
        setNotFound(true);
      } else {
        setError(msg);
      }
    } finally {
      setLoading(false);
    }
  }, [jobId]);

  const runResearch = useCallback(async () => {
    setRunning(true);
    setResearchDone(false);
    setError(null);
    setNotFound(false);
    try {
      const result = await api.jobs.companyResearch.run(jobId, !!data);
      setData(result);
      setNotFound(false);
      setResearchDone(true);
      window.dispatchEvent(new Event("company-research-complete"));
      setTimeout(() => {
        setRunning(false);
        setResearchDone(false);
      }, 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research failed");
      setRunning(false);
      setResearchDone(false);
      window.dispatchEvent(new Event("company-research-failed"));
    }
  }, [jobId, data]);

  useEffect(() => {
    // Load the resource whenever the route job changes.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    loadResearch();
  }, [loadResearch]);

  useEffect(() => {
    function onRunResearch() {
      runResearch();
    }
    window.addEventListener("run-research-triggered", onRunResearch);
    return () => window.removeEventListener("run-research-triggered", onRunResearch);
  }, [runResearch]);

  return (
    <CollapsibleCard
      title="Company Research"
      icon={Building2}
      description={
        data
          ? `Researched ${new Date(data.researched_at).toLocaleDateString()}`
          : "Funding, sentiment, and fit analysis"
      }
      action={
        <div className="flex items-center gap-1">
          <Button
            variant="outline"
            size="sm"
            disabled={running}
            onClick={runResearch}
          >
            {running ? (
              <Loader2 className="animate-spin" />
            ) : (
              <RefreshCw />
            )}
            {running ? "Researching..." : data ? "Refresh" : "Research"}
          </Button>
          {data && (
            <CopyResearchButton data={data} />
          )}
        </div>
      }
    >
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading company research…
          </div>
        )}

        {error && (
          <ErrorBanner message={error} />
        )}

        {notFound && !loading && !running && (
          <div className="flex flex-col gap-2 text-sm text-muted-foreground">
            <p>No company research yet. Click &ldquo;Research&rdquo; to gather information.</p>
          </div>
        )}

        {running && (
          <ResearchProgress done={researchDone} />
        )}

        {data && !running && (
          <>
            {/* Sources used */}
            {data.sources_used.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {data.sources_used.map((src) => (
                  <Badge key={src} variant="secondary" className="text-xs">
                    {src}
                  </Badge>
                ))}
              </div>
            )}

            {/* Summary + overall confidence */}
            {data.summary && (
              <div className="flex flex-col gap-1.5">
                <p className="text-sm leading-relaxed">{data.summary}</p>
                <div className="flex items-center gap-2">
                  <ConfidenceBadge confidence={data.overall_confidence} />
                </div>
              </div>
            )}

            {/* Research-adjusted score */}
            {data.research_adjusted_score != null && data.research_adjustment_applied && (
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <TrendingUp className="size-4 text-muted-foreground" />
                  Research-Adjusted Score
                </div>
                <div className="flex items-center gap-3">
                  <div className="flex items-baseline gap-1.5">
                    <span className="text-2xl font-bold tabular-nums">
                      {data.research_adjusted_score.toFixed(1)}
                    </span>
                    {data.research_delta !== 0 && (
                      <span className={`text-sm font-medium ${data.research_delta > 0 ? "text-emerald-600" : "text-destructive"}`}>
                        ({data.research_delta > 0 ? "+" : ""}{data.research_delta.toFixed(1)})
                      </span>
                    )}
                  </div>
                  <Badge variant="outline" className="text-xs text-muted-foreground">
                    base {data.research_adjusted_score - data.research_delta !== 0 ? (data.research_adjusted_score - data.research_delta).toFixed(1) : "—"}
                  </Badge>
                </div>
                {data.research_breakdown.length > 0 && (
                  <div className="flex flex-col gap-1">
                    {data.research_breakdown.map((item, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs">
                        {item.delta > 0 ? (
                          <CheckCircle2 className="size-3 shrink-0 text-emerald-600" />
                        ) : (
                          <XCircle className="size-3 shrink-0 text-destructive" />
                        )}
                        <span className="font-medium capitalize">
                          {item.factor.replace(/_/g, " ")}
                        </span>
                        <span className={item.delta > 0 ? "text-emerald-600" : "text-destructive"}>
                          {item.delta > 0 ? "+" : ""}{item.delta.toFixed(1)}
                        </span>
                        <Badge variant="outline" className="text-xs text-muted-foreground ml-auto">
                          {Math.round(item.confidence * 100)}% · {item.source_section}
                        </Badge>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            )}

            {/* Verdict flags */}
            {(data.verdict_flags.green.length > 0 ||
              data.verdict_flags.red.length > 0 ||
              data.verdict_flags.watch.length > 0) && (
              <div className="flex flex-col gap-1.5 border-t border-border pt-3">
                <VerdictFlagRow items={data.verdict_flags.green} icon={CheckCircle2} color="text-emerald-600" />
                <VerdictFlagRow items={data.verdict_flags.red} icon={XCircle} color="text-destructive" />
                <VerdictFlagRow items={data.verdict_flags.watch} icon={Eye} color="text-amber-600" />
              </div>
            )}

            {/* Wikipedia section */}
            {data.wikipedia && (
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Globe className="size-4 text-muted-foreground" />
                  About
                </div>
                {data.wikipedia.thumbnail && (
                  // Remote Wikipedia thumbnails are dynamic and not configured for Next image optimization.
                  // eslint-disable-next-line @next/next/no-img-element
                  <img
                    src={data.wikipedia.thumbnail}
                    alt={data.wikipedia.title}
                    className="h-32 w-auto rounded-md border border-border object-cover"
                  />
                )}
                <p className="text-sm text-muted-foreground leading-relaxed">
                  {data.wikipedia.extract}
                </p>
                {data.wikipedia.url && (
                  <a
                    href={data.wikipedia.url}
                    target="_blank"
                    rel="noopener noreferrer"
                    className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                  >
                    Wikipedia <ExternalLink className="size-3" />
                  </a>
                )}
              </div>
            )}

            {/* Funding section */}
            {data.funding && (
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <TrendingUp className="size-4 text-muted-foreground" />
                  Funding & Stage
                  <ConfidenceBadge confidence={data.funding.confidence} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  {data.funding.stage && (
                    <div>
                      <span className="text-muted-foreground">Stage: </span>
                      <span className="font-medium">{data.funding.stage}</span>
                    </div>
                  )}
                  {data.funding.public && (
                    <div>
                      <span className="text-muted-foreground">Public: </span>
                      <span className="font-medium">Yes</span>
                    </div>
                  )}
                  {data.funding.founded && (
                    <div>
                      <span className="text-muted-foreground">Founded: </span>
                      <span className="font-medium">{data.funding.founded}</span>
                    </div>
                  )}
                  {data.funding.hq && (
                    <div>
                      <span className="text-muted-foreground">HQ: </span>
                      <span className="font-medium">{data.funding.hq}</span>
                    </div>
                  )}
                  {data.funding.total_raised_usd != null && (
                    <div>
                      <span className="text-muted-foreground">Total raised: </span>
                      <span className="font-medium">${(data.funding.total_raised_usd / 1e6).toFixed(0)}M</span>
                    </div>
                  )}
                  {data.funding.valuation_usd != null && (
                    <div>
                      <span className="text-muted-foreground">Valuation: </span>
                      <span className="font-medium">${(data.funding.valuation_usd / 1e6).toFixed(0)}M</span>
                    </div>
                  )}
                  {data.funding.headcount != null && (
                    <div>
                      <span className="text-muted-foreground">Headcount: </span>
                      <span className="font-medium">{data.funding.headcount.toLocaleString()}</span>
                    </div>
                  )}
                  {data.funding.headcount_trend && (
                    <div>
                      <span className="text-muted-foreground">Trend: </span>
                      <span className="font-medium capitalize">{data.funding.headcount_trend}</span>
                    </div>
                  )}
                  {data.funding.financial_health && (
                    <div>
                      <span className="text-muted-foreground">Health: </span>
                      <span className="font-medium capitalize">{data.funding.financial_health}</span>
                    </div>
                  )}
                </div>
                {data.funding.last_round && (data.funding.last_round.type || data.funding.last_round.amount_usd) && (
                  <div className="flex items-center gap-2 text-xs text-muted-foreground">
                    <Badge variant="outline" className="text-xs">
                      {data.funding.last_round.type || "Last round"}
                    </Badge>
                    {data.funding.last_round.amount_usd != null && (
                      <span>${(data.funding.last_round.amount_usd / 1e6).toFixed(0)}M</span>
                    )}
                    {data.funding.last_round.date && <span>· {data.funding.last_round.date}</span>}
                    {data.funding.last_round.lead_investors.length > 0 && (
                      <span>· {data.funding.last_round.lead_investors.join(", ")}</span>
                    )}
                  </div>
                )}
                {data.funding.layoffs.length > 0 && (
                  <div className="flex flex-col gap-1">
                    {data.funding.layoffs.map((layoff, i) => (
                      <div key={i} className="flex items-center gap-2 text-xs text-destructive">
                        <AlertCircle className="size-3 shrink-0" />
                        {layoff.date && <span>{layoff.date}</span>}
                        {layoff.pct != null && <span>({layoff.pct}%)</span>}
                        {layoff.count != null && <span>· {layoff.count} employees</span>}
                        {layoff.source && <span>· {layoff.source}</span>}
                      </div>
                    ))}
                  </div>
                )}
                {data.funding.sources.length > 0 && (
                  <div className="flex flex-wrap gap-1 items-center">
                    {data.funding.sources.map((src, i) => (
                      <a
                        key={i}
                        href={src.url}
                        target="_blank"
                        rel="noopener noreferrer"
                        className="text-xs text-primary hover:underline inline-flex items-center gap-1"
                      >
                        Source <ExternalLink className="size-3" />
                      </a>
                    ))}
                    <StrippedBadge count={data.funding.stripped_count} />
                  </div>
                )}
                {data.funding.sources.length === 0 && data.funding.stripped_count > 0 && (
                  <StrippedBadge count={data.funding.stripped_count} />
                )}
              </div>
            )}

            {/* Sentiment section */}
            {data.sentiment && (
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Users className="size-4 text-muted-foreground" />
                  Employee Sentiment
                  <ConfidenceBadge confidence={data.sentiment.confidence} />
                  <StrippedBadge count={data.sentiment.stripped_count} />
                </div>
                {data.sentiment.overall_rating_estimate != null && (
                  <div className="flex items-center gap-3 rounded-md bg-muted p-2.5">
                    <span className="text-lg font-semibold">
                      {data.sentiment.overall_rating_estimate.toFixed(1)}
                    </span>
                    <span className="text-xs text-muted-foreground">{data.sentiment.rating_scale}</span>
                    {data.sentiment.ceo_approval_pct != null && (
                      <Badge variant="outline" className="text-xs ml-auto">
                        CEO: {data.sentiment.ceo_approval_pct.toFixed(0)}%
                      </Badge>
                    )}
                    {data.sentiment.recommend_pct != null && (
                      <Badge variant="outline" className="text-xs">
                        Recommend: {data.sentiment.recommend_pct.toFixed(0)}%
                      </Badge>
                    )}
                  </div>
                )}
                {data.sentiment.positives.length > 0 && (
                  <div className="flex flex-col gap-1">
                    {data.sentiment.positives.map((theme, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        <CheckCircle2 className="size-3 shrink-0 mt-0.5 text-emerald-600" />
                        <div>
                          <span className="font-medium">{theme.theme}</span>
                          <Badge variant="outline" className="ml-1 text-xs">{theme.frequency}</Badge>
                          {theme.age_months != null && (
                            <span className="text-muted-foreground ml-1">· {theme.age_months}mo old</span>
                          )}
                          {theme.paraphrase && (
                            <p className="text-muted-foreground mt-0.5">{theme.paraphrase}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {data.sentiment.negatives.length > 0 && (
                  <div className="flex flex-col gap-1">
                    {data.sentiment.negatives.map((theme, i) => (
                      <div key={i} className="flex items-start gap-2 text-xs">
                        <XCircle className="size-3 shrink-0 mt-0.5 text-destructive" />
                        <div>
                          <span className="font-medium">{theme.theme}</span>
                          <Badge variant="outline" className="ml-1 text-xs">{theme.frequency}</Badge>
                          {theme.age_months != null && (
                            <span className="text-muted-foreground ml-1">· {theme.age_months}mo old</span>
                          )}
                          {theme.paraphrase && (
                            <p className="text-muted-foreground mt-0.5">{theme.paraphrase}</p>
                          )}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
                {data.sentiment.staleness_warning && (
                  <p className="text-xs text-amber-600">{data.sentiment.staleness_warning}</p>
                )}
              </div>
            )}

            {/* Fit section */}
            {data.fit && (
              <div className="flex flex-col gap-2 border-t border-border pt-3">
                <div className="flex items-center gap-2 text-sm font-medium">
                  <Briefcase className="size-4 text-muted-foreground" />
                  Fit Signals
                  <ConfidenceBadge confidence={data.fit.confidence} />
                  <StrippedBadge count={data.fit.stripped_count} />
                </div>
                <div className="grid grid-cols-2 gap-2 text-sm">
                  {data.fit.remote_policy && (
                    <div className="flex items-center gap-1">
                      <MapPin className="size-3 text-muted-foreground" />
                      <span className="text-muted-foreground">Remote: </span>
                      <span className="font-medium capitalize">{data.fit.remote_policy}</span>
                    </div>
                  )}
                  {data.fit.size_bucket && (
                    <div>
                      <span className="text-muted-foreground">Size: </span>
                      <span className="font-medium">{data.fit.size_bucket}</span>
                    </div>
                  )}
                  {data.fit.ic_vs_mgmt_culture && (
                    <div>
                      <span className="text-muted-foreground">Culture: </span>
                      <span className="font-medium">{data.fit.ic_vs_mgmt_culture}</span>
                    </div>
                  )}
                  {data.fit.comp_band && (
                    <div>
                      <span className="text-muted-foreground">Comp: </span>
                      <span className="font-medium">{data.fit.comp_band}</span>
                    </div>
                  )}
                  {data.fit.clearance_required && (
                    <div className="flex items-center gap-1 text-amber-600">
                      <ShieldAlert className="size-3" />
                      <span className="font-medium">Clearance required</span>
                    </div>
                  )}
                </div>
                {data.fit.remote_walkback && (
                  <p className="text-xs text-amber-600">
                    <Heart className="size-3 inline mr-1" />
                    {data.fit.remote_walkback}
                  </p>
                )}
              </div>
            )}

            {/* Gaps */}
            {data.gaps.length > 0 && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                <span className="text-xs font-medium text-muted-foreground">Data gaps:</span>
                <div className="flex flex-wrap gap-1.5">
                  {data.gaps.map((gap, i) => (
                    <Badge key={i} variant="outline" className="text-xs text-muted-foreground">
                      {gap}
                    </Badge>
                  ))}
                </div>
              </div>
            )}

            {/* Errors */}
            {data.errors.length > 0 && (
              <div className="flex flex-col gap-1 border-t border-border pt-3">
                {data.errors.map((err, i) => (
                  <div key={i} className="flex items-center gap-2 text-xs text-muted-foreground">
                    <AlertCircle className="size-3 shrink-0" />
                    {err}
                  </div>
                ))}
              </div>
            )}
          </>
        )}
    </CollapsibleCard>
  );
}
