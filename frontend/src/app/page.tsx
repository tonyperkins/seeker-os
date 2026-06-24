import Link from "next/link";
import { redirect } from "next/navigation";
import {
  XCircle,
  Clock,
  ArrowRight,
  Trophy,
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
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { RunPipelineButton } from "@/components/run-pipeline-button";
import { api, type FunnelStats, type FunnelStage, type PipelineRunRecord, type JobSummary, type SettingsResponse, type MasterResumeInfo, type ProvidersConfigResponse } from "@/lib/api";
import { formatDateTime } from "@/lib/date";


function RunStatusBadge({ status }: { status: string }) {
  const variant =
    status === "completed"
      ? "default"
      : status === "running"
        ? "secondary"
        : status === "failed"
          ? "destructive"
          : "outline";
  return <Badge variant={variant}>{status}</Badge>;
}

const STAGE_COLORS: Record<number, string> = {
  1: "bg-sky-500/80 dark:bg-sky-600/80",
  2: "bg-indigo-500/80 dark:bg-indigo-600/80",
  4: "bg-purple-500/80 dark:bg-purple-600/80",
};

function FunnelChart({ stages }: { stages: FunnelStage[] }) {
  // Nested funnel: each stage is a subset of the previous one. The full bar is
  // the largest stage (discovered); smaller stages are left-aligned overlays
  // sized relative to the largest, layered so the smallest sits on top.
  const ordered = [...stages].sort((a, b) => b.count - a.count);
  const max = ordered[0]?.count || 1;

  const n = ordered.length;

  return (
    <div className="flex flex-col gap-4">
      {/* Nested bar — each stage is narrower AND shorter than its parent,
          aligned to the bottom so containment reads naturally. */}
      <div className="relative h-16 w-full">
        {ordered.map((stage, i) => {
          const widthPct = (stage.count / max) * 100;
          const heightPct = n > 1 ? 100 - (i * 60) / (n - 1) : 100;
          const color = STAGE_COLORS[stage.tier] || "bg-primary/60";
          return (
            <div
              key={stage.label}
              className={`absolute bottom-0 left-0 flex items-center justify-end rounded-t-md border-x border-t border-background/60 px-2.5 text-sm font-semibold text-white shadow-sm transition-all ${color}`}
              style={{
                width: `${widthPct}%`,
                height: `${heightPct}%`,
                zIndex: i + 1,
              }}
              title={`${stage.label}: ${stage.count}`}
            >
              {widthPct > 6 && stage.count}
            </div>
          );
        })}
      </div>

      {/* Legend — smallest to largest (scoring → filters → discovered) */}
      <div className="flex flex-wrap items-center gap-x-5 gap-y-2">
        {[...ordered].reverse().map((stage) => {
          const color = STAGE_COLORS[stage.tier] || "bg-primary/60";
          const pctOfTotal = Math.round((stage.count / max) * 100);
          return (
            <Link
              key={stage.label}
              href={`/jobs?min_tier=${stage.tier}`}
              className="flex items-center gap-2 text-sm transition-opacity hover:opacity-70"
            >
              <span className={`size-3 shrink-0 rounded-sm ${color}`} />
              <span className="text-muted-foreground">{stage.label}</span>
              <span className="font-mono font-semibold">{stage.count}</span>
              <span className="font-mono text-xs text-muted-foreground">({pctOfTotal}%)</span>
            </Link>
          );
        })}
      </div>
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

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
          <p className="text-sm text-muted-foreground">
            Pipeline funnel, recent runs, and top matches.
          </p>
        </div>
      </div>

      {/* Pipeline funnel */}
      {funnelStages.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>Pipeline Funnel</CardTitle>
            <CardDescription>
              Cumulative jobs surviving each stage — narrowing toward scored
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

      {/* Run pipeline + recent runs */}
      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-1">
          <CardHeader>
            <CardTitle>Run Pipeline</CardTitle>
            <CardDescription>
              Execute the full tiered pipeline on demand.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <RunPipelineButton />
          </CardContent>
        </Card>

        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>Recent Pipeline Runs</CardTitle>
            <CardDescription>Latest execution history</CardDescription>
            <CardAction>
              <Link href="/queries" className={buttonVariants({ variant: "ghost", size: "sm" })}>
                Manage queries
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
                {runs.slice(0, 8).map((run) => (
                  <div key={run.id} className="flex items-center gap-3 py-2.5 text-sm">
                    <Clock className="size-4 text-muted-foreground" />
                    <span className="text-muted-foreground">{formatDateTime(run.started_at)}</span>
                    <span className="font-mono text-xs text-muted-foreground">
                      {run.run_id.slice(0, 8)}
                    </span>
                    <span className="text-muted-foreground">
                      {run.cards_new} new · {run.jobs_ready} ready
                    </span>
                    <span className="ml-auto">
                      <RunStatusBadge status={run.status} />
                    </span>
                  </div>
                ))}
              </div>
            )}
          </CardContent>
        </Card>
      </div>

      {/* Top matches */}
      <Card>
        <CardHeader>
          <CardTitle>Top Matches</CardTitle>
          <CardDescription>Highest-scoring ready jobs</CardDescription>
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
              {topMatches.map((job) => (
                <Link
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
                >
                  <Trophy className="size-4 text-amber-500" />
                  <span className="font-medium">{job.title}</span>
                  <span className="text-muted-foreground">{job.company}</span>
                  {job.score != null && (
                    <Badge variant="secondary" className="ml-auto">
                      {job.score}
                    </Badge>
                  )}
                  <ArrowRight className="size-4 text-muted-foreground" />
                </Link>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
