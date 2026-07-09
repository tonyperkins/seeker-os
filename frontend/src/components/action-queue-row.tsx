"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowRight, Trophy, Sparkles, FileText, SkipForward, Loader2 } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { VerdictBadge } from "@/components/verdict-badge";
import { api, type JobSummary, type SkipReasonOption } from "@/lib/api";

function CappedScore({ score, netScore }: { score: number | null; netScore: number | null }) {
  if (score == null && netScore == null) {
    return <span className="font-mono text-sm text-muted-foreground">—</span>;
  }

  const effective = netScore ?? score;
  const isCapped = netScore != null && score != null && netScore < score;

  if (isCapped) {
    return (
      <span className="flex shrink-0 items-baseline gap-1 font-mono text-sm">
        <span className="text-muted-foreground line-through decoration-muted-foreground/50">
          {score!.toFixed(1)}
        </span>
        <ArrowRight className="size-3 text-muted-foreground" />
        <span className="font-semibold text-foreground">{effective!.toFixed(1)}</span>
      </span>
    );
  }

  return (
    <span className="w-12 shrink-0 text-right font-mono font-semibold">
      {effective!.toFixed(1)}
    </span>
  );
}

function CompLocation({ job }: { job: JobSummary }) {
  const parts: string[] = [];
  if (job.comp_max) {
    parts.push(`$${(job.comp_max / 1000).toFixed(0)}k`);
  }
  if (job.location) {
    parts.push(job.location);
  }
  if (job.workplace_type && job.workplace_type !== "Unknown") {
    parts.push(job.workplace_type);
  }
  const text = parts.join(" · ");

  if (!text) return null;

  return (
    <span className="block truncate text-xs text-muted-foreground">{text}</span>
  );
}

function getTopSignal(job: JobSummary): string | null {
  // For verdict rows: top-weighted positive signal
  // For capped rows: cap reason (net < score means verdict cap applied)
  // For not-analyzed rows: top rubric signal from score_reasons
  if (job.has_analysis && job.analysis_verdict) {
    // If capped, show cap reason
    if (job.net_score != null && job.score != null && job.net_score < job.score) {
      return `capped by ${job.analysis_verdict} verdict`;
    }
    // Otherwise show top positive signal
    if (job.score_modifiers) {
      const positive = Object.entries(job.score_modifiers)
        .filter(([, pts]) => pts > 0)
        .sort((a, b) => b[1] - a[1]);
      if (positive.length > 0) {
        return `+${positive[0][1].toFixed(1)} ${positive[0][0]}`;
      }
    }
  }
  // For not-analyzed: top score reason
  if (job.score_reasons && job.score_reasons.length > 0) {
    // Find the first non-Base reason, or the first reason
    const nonBase = job.score_reasons.find((r) => !r.startsWith("Base:"));
    return nonBase ?? job.score_reasons[0];
  }
  return null;
}

export function ActionQueueRow({ job, rank }: { job: JobSummary; rank: number }) {
  const [analyzing, setAnalyzing] = useState(false);
  const [analyzeError, setAnalyzeError] = useState<string | null>(null);
  const [skipOpen, setSkipOpen] = useState(false);
  const [skipping, setSkipping] = useState(false);
  const [skipReasons, setSkipReasons] = useState<SkipReasonOption[] | null>(null);
  const [generating, setGenerating] = useState(false);
  const [genError, setGenError] = useState<string | null>(null);

  const topSignal = getTopSignal(job);
  const aiPolicy = job.ai_policy;
  const docsDisabled = aiPolicy === "forbidden";
  const docsTooltip = docsDisabled ? "AI generation forbidden for this job" : undefined;

  async function handleAnalyze() {
    setAnalyzing(true);
    setAnalyzeError(null);
    try {
      await api.jobs.analysis.run(job.id);
      // Reload the page to reflect the new analysis
      window.location.reload();
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Analysis failed");
    } finally {
      setAnalyzing(false);
    }
  }

  async function handleGenerateDocs() {
    setGenerating(true);
    setGenError(null);
    try {
      await api.resumes.generate(job.id);
      window.location.href = `/jobs/${job.id}`;
    } catch (err) {
      setGenError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setGenerating(false);
    }
  }

  async function handleSkip(reason?: string) {
    setSkipping(true);
    try {
      await api.jobs.skip(job.id, reason);
      window.location.reload();
    } catch (err) {
      setAnalyzeError(err instanceof Error ? err.message : "Skip failed");
    } finally {
      setSkipping(false);
      setSkipOpen(false);
    }
  }

  async function openSkipPicker() {
    if (!skipReasons) {
      try {
        const settings = await api.settings.get();
        setSkipReasons(settings.skip_reasons ?? []);
      } catch {
        setSkipReasons([]);
      }
    }
    setSkipOpen(true);
  }

  return (
    <div className="flex flex-col gap-1 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md">
      <div className="flex items-center gap-3">
        {rank === 0 ? (
          <Trophy className="size-4 shrink-0 text-amber-500" />
        ) : (
          <span className="w-4 shrink-0 text-center font-mono text-xs text-muted-foreground">
            {rank + 1}
          </span>
        )}
        <Link href={`/jobs/${job.id}`} className="min-w-0 flex-1">
          <span className="block truncate font-medium hover:underline">{job.title}</span>
          <span className="block truncate text-muted-foreground">{job.company}</span>
          <CompLocation job={job} />
        </Link>
        <VerdictBadge verdict={job.analysis_verdict} hasAnalysis={job.has_analysis} />
        <CappedScore score={job.score} netScore={job.net_score} />
        <Link
          href={`/jobs/${job.id}`}
          className={buttonVariants({ variant: "ghost", size: "sm" })}
        >
          <ArrowRight className="size-4" />
        </Link>
      </div>

      {/* Reason line (B2) */}
      {topSignal && (
        <div className="ml-7 truncate text-xs text-muted-foreground/70">
          {topSignal}
        </div>
      )}

      {/* Row actions (B1 + B3) */}
      <div className="ml-7 flex items-center gap-2">
        {/* B1: Analyze button for not-analyzed jobs */}
        {!job.has_analysis && (
          <button
            onClick={handleAnalyze}
            disabled={analyzing}
            className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            {analyzing ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <Sparkles className="size-3" />
            )}
            Analyze
          </button>
        )}
        {analyzeError && (
          <span className="text-xs text-destructive">{analyzeError}</span>
        )}

        {/* B3: Generate docs — respects ai_policy */}
        {aiPolicy !== "forbidden" && (
          <button
            onClick={handleGenerateDocs}
            disabled={generating || docsDisabled}
            title={docsTooltip}
            className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            {generating ? (
              <Loader2 className="size-3 animate-spin" />
            ) : (
              <FileText className="size-3" />
            )}
            Generate docs
          </button>
        )}
        {aiPolicy === "forbidden" && (
          <span className="flex items-center gap-1 text-xs text-muted-foreground/50" title={docsTooltip}>
            <FileText className="size-3" />
            Docs (forbidden)
          </span>
        )}
        {genError && (
          <span className="text-xs text-destructive">{genError}</span>
        )}

        {/* B3: Skip button */}
        {!skipOpen ? (
          <button
            onClick={openSkipPicker}
            disabled={skipping}
            className="flex items-center gap-1 text-xs text-muted-foreground transition-colors hover:text-foreground disabled:opacity-50"
          >
            <SkipForward className="size-3" />
            Skip
          </button>
        ) : (
          <div className="flex flex-wrap items-center gap-1">
            {skipReasons && skipReasons.length > 0 ? (
              skipReasons.map((r) => (
                <button
                  key={r.key}
                  onClick={() => handleSkip(r.key)}
                  disabled={skipping}
                  className="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
                >
                  {r.label}
                </button>
              ))
            ) : (
              <button
                onClick={() => handleSkip()}
                disabled={skipping}
                className="rounded border border-border px-1.5 py-0.5 text-xs text-muted-foreground transition-colors hover:bg-muted disabled:opacity-50"
              >
                Confirm skip
              </button>
            )}
            <button
              onClick={() => setSkipOpen(false)}
              className="text-xs text-muted-foreground/60 hover:text-foreground"
            >
              Cancel
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
