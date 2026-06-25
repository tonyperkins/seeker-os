"use client";

import { useState, useEffect, useRef } from "react";
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
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { api, type CompanyResearchResult } from "@/lib/api";

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
              isPending ? "text-muted-foreground/40" : "text-foreground"
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

export function CompanyResearch({ jobId }: { jobId: number }) {
  const [data, setData] = useState<CompanyResearchResult | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [researchDone, setResearchDone] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notFound, setNotFound] = useState(false);

  async function loadResearch() {
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
  }

  async function runResearch() {
    setRunning(true);
    setResearchDone(false);
    setError(null);
    setNotFound(false);
    try {
      const result = await api.jobs.companyResearch.run(jobId);
      setData(result);
      setNotFound(false);
      setResearchDone(true);
      setTimeout(() => {
        setRunning(false);
        setResearchDone(false);
      }, 600);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Research failed");
      setRunning(false);
      setResearchDone(false);
    }
  }

  useEffect(() => {
    loadResearch();
  }, [jobId]);

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
          {data ? "Refresh" : "Research"}
        </Button>
      }
    >
        {loading && (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 className="size-4 animate-spin" />
            Loading company research…
          </div>
        )}

        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            {error}
          </div>
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
