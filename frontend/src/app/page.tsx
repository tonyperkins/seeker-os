import Link from "next/link";
import { redirect } from "next/navigation";
import {
  CheckCircle2,
  Clock,
  ArrowRight,
  Trophy,
  XCircle,
  FileSearch,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardAction,
} from "@/components/ui/card";
import { buttonVariants } from "@/components/ui/button";
import { RunStrip } from "@/components/run-strip";
import { VerdictBadge } from "@/components/verdict-badge";
import { RefilterRescoreButton } from "@/components/refilter-rescore-button";
import { api, type FunnelStats, type FunnelStage, type PipelineRunRecord, type JobSummary, type SettingsResponse, type MasterResumeInfo, type ProvidersConfigResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/date";

export const dynamic = "force-dynamic";

const STAGE_COLORS: Record<number, string> = {
  1: "bg-sky-500 dark:bg-sky-600",
  2: "bg-indigo-500 dark:bg-indigo-600",
  4: "bg-purple-500 dark:bg-purple-600",
};

function FunnelChart({ stages }: { stages: FunnelStage[] }) {
  const ordered = [...stages].sort((a, b) => a.tier - b.tier);
  const max = ordered[0]?.count || 1;

  return (
    <div className="flex flex-col gap-3">
      {ordered.map((stage) => {
        const pct = max > 0 ? (stage.count / max) * 100 : 0;
        const color = STAGE_COLORS[stage.tier] || "bg-primary";
        return (
          <div key={stage.label} className="flex flex-col gap-1">
            <div className="flex items-baseline justify-between text-sm">
              <Link
                href={`/jobs?min_tier=${stage.tier}`}
                className="text-muted-foreground transition-opacity hover:opacity-70"
              >
                {stage.label}
              </Link>
              <span className="font-mono text-xs">
                <span className="font-semibold text-foreground">{stage.count}</span>
                <span className="ml-1.5 text-muted-foreground">
                  {pct > 0 ? `${Math.round(pct)}%` : "0%"}
                </span>
              </span>
            </div>
            <div className="h-2.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className={`h-full rounded-full transition-all ${color}`}
                style={{ width: `${Math.max(pct, 2)}%` }}
              />
            </div>
          </div>
        );
      })}
    </div>
  );
}

export default async function DashboardPage() {
  let funnel: FunnelStats | null = null;
  let runs: PipelineRunRecord[] = [];
  let topMatches: JobSummary[] = [];
  let settings: SettingsResponse | null = null;
  let resumeInfo: MasterResumeInfo | null = null;
  let providers: ProvidersConfigResponse | null = null;
  let error: string | null = null;

  try {
    [funnel, runs, topMatches, settings, resumeInfo, providers] = await Promise.all([
      api.analytics.funnel(),
      api.pipeline.runs(),
      api.jobs.list({ status: "ready", limit: 5 }),
      api.settings.get(),
      api.resumes.getMaster().catch(() => null),
      api.models.getConfig().catch(() => null),
    ]);
    // Sort top matches by score desc (defensive — API may already sort)
    topMatches = [...topMatches].sort((a, b) => (b.score ?? 0) - (a.score ?? 0)).slice(0, 5);
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load dashboard data";
  }

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <Card>
          <CardContent className="py-10 text-center text-destructive">
            {error}
          </CardContent>
        </Card>
      </div>
    );
  }

  // Check if setup is complete — redirect to onboarding if not
  const hasProvider = (providers?.providers ?? []).some(
    (p) => p.enabled && p.api_key_set && p.models.length > 0,
  );
  const tiers = providers?.tiers ?? {};
  const providerList = providers?.providers ?? [];
  const tierIsValid = (tier: typeof tiers[keyof typeof tiers]) => {
    if (!tier?.model || !tier?.provider) return false;
    const prov = providerList.find((p) => p.id === tier.provider);
    return !!prov && prov.api_key_set && prov.models.some((m) => m.id === tier.model);
  };
  const tiersConfigured = tierIsValid(tiers.heavy) && tierIsValid(tiers.moderate) && tierIsValid(tiers.light);
  const isProfileConfigured = settings?.profile_configured ?? false;
  const hasResume = resumeInfo?.exists ?? false;
  const setupComplete = hasProvider && tiersConfigured && isProfileConfigured && hasResume;

  if (!setupComplete) {
    redirect("/onboarding");
  }

  const funnelStages = funnel?.funnel ?? [];
  const jdFetchTotal = funnel?.jd_fetch_total ?? 0;
  const jdFetchSuccess = funnel?.jd_fetch_success ?? 0;
  const jdFetchPct = jdFetchTotal > 0 ? Math.round((jdFetchSuccess / jdFetchTotal) * 100) : 0;

  const lastRun = runs.length > 0 ? runs[0] : null;

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <p className="text-sm text-muted-foreground">
          Run the pipeline, review recent runs, act on top matches.
        </p>
      </div>

      {/* ZONE 1 — Run strip (self-contained, removable) */}
      <RunStrip
        lastRun={lastRun ? {
          started_at: lastRun.started_at,
          cards_new: lastRun.cards_new,
          jobs_ready: lastRun.jobs_ready,
        } : null}
      />

      {/* ZONE 2 — Recent runs + cumulative funnel (two columns) */}
      <div className="grid gap-4 lg:grid-cols-[1.1fr_1fr]">
        {/* Left — Recent runs */}
        <Card>
          <CardHeader>
            <CardTitle>Recent Runs</CardTitle>
            <CardDescription>Latest pipeline execution history</CardDescription>
            <CardAction>
              <Link href="/jobs" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                View all
                <ArrowRight />
              </Link>
            </CardAction>
          </CardHeader>
          <CardContent>
            {runs.length === 0 ? (
              <p className="py-6 text-center text-sm text-muted-foreground">
                No pipeline runs yet.
              </p>
            ) : (
              <div className="flex flex-col divide-y divide-border">
                {runs.slice(0, 5).map((run) => (
                  <div
                    key={run.id}
                    className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
                  >
                    <Link
                      href={`/jobs?run_id=${run.run_id}&status=ready`}
                      className="flex flex-1 items-center gap-3"
                    >
                      {run.status === "completed" ? (
                        <CheckCircle2 className="size-4 shrink-0 text-emerald-500" />
                      ) : run.status === "failed" ? (
                        <XCircle className="size-4 shrink-0 text-destructive" />
                      ) : (
                        <Clock className="size-4 shrink-0 text-muted-foreground" />
                      )}
                      <div className="flex flex-col">
                        <span className="text-muted-foreground">{formatDateTime(run.started_at)}</span>
                        <span className="font-mono text-xs text-muted-foreground/70">
                          {run.run_id.slice(0, 8)}
                        </span>
                      </div>
                      <div className="ml-auto flex items-center gap-4 font-mono text-xs">
                        <div className="flex flex-col items-end">
                          <span className="font-semibold">{run.cards_fetched}</span>
                          <span className="text-muted-foreground/70">fetched</span>
                        </div>
                        <div className="flex flex-col items-end">
                          <span className="font-semibold">{run.cards_new}</span>
                          <span className="text-muted-foreground/70">new</span>
                        </div>
                        <div className="flex flex-col items-end">
                          <span className="font-bold text-emerald-600 dark:text-emerald-400">{run.jobs_ready}</span>
                          <span className="text-muted-foreground/70">ready</span>
                        </div>
                      </div>
                    </Link>
                    <RefilterRescoreButton runId={run.run_id} label="" size="icon" variant="ghost" />
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>

        {/* Right — Pipeline funnel (fixed) */}
        {funnelStages.length > 0 && (
          <Card>
            <CardHeader>
              <CardTitle>Pipeline Funnel</CardTitle>
              <CardDescription>
                Cumulative jobs surviving each stage
              </CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <FunnelChart stages={funnelStages} />
              <div className="flex flex-wrap gap-x-6 gap-y-2 border-t border-border pt-3 text-sm">
                <div className="flex items-center gap-2">
                  <XCircle className="size-4 text-destructive" />
                  <span className="text-muted-foreground">Rejected</span>
                  <span className="font-mono font-semibold">{funnel?.rejected ?? 0}</span>
                </div>
                <div className="flex items-center gap-2">
                  <FileSearch className="size-4 text-muted-foreground" />
                  <span className="text-muted-foreground">JD Fetch</span>
                  <span className="font-mono font-semibold">
                    {jdFetchTotal > 0 ? `${jdFetchSuccess}/${jdFetchTotal}` : "—"}
                  </span>
                  {jdFetchTotal > 0 && (
                    <span className="font-mono text-xs text-muted-foreground">({jdFetchPct}%)</span>
                  )}
                </div>
              </div>
            </CardContent>
          </Card>
        )}
      </div>

      {/* ZONE 3 — Top matches with verdict */}
      <Card>
        <CardHeader>
          <CardTitle>Top Matches</CardTitle>
          <CardDescription>Highest-scoring ready jobs with AI verdict</CardDescription>
          <CardAction>
            <Link href="/jobs?status=ready" className={buttonVariants({ variant: "ghost", size: "sm" })}>
              View all
              <ArrowRight />
            </Link>
          </CardAction>
        </CardHeader>
        <CardContent>
          {topMatches.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No ready jobs yet. Run the pipeline to discover matches.
            </p>
          ) : (
            <div className="flex flex-col divide-y divide-border">
              {topMatches.map((job, i) => (
                <Link
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
                >
                  {i === 0 ? (
                    <Trophy className="size-4 shrink-0 text-amber-500" />
                  ) : (
                    <span className="w-4 shrink-0 text-center font-mono text-xs text-muted-foreground">
                      {i + 1}
                    </span>
                  )}
                  <div className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{job.title}</span>
                    <span className="block truncate text-muted-foreground">{job.company}</span>
                  </div>
                  <VerdictBadge verdict={job.analysis_verdict} hasAnalysis={job.has_analysis} />
                  {job.score != null && (
                    <span className="w-10 shrink-0 text-right font-mono font-semibold">
                      {job.score}
                    </span>
                  )}
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
