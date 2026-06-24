import Link from "next/link";
import { redirect } from "next/navigation";
import {
  CheckCircle2,
  XCircle,
  Layers,
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

function StatCard({
  label,
  value,
  icon: Icon,
  tone = "default",
}: {
  label: string;
  value: number | string;
  icon: React.ComponentType<{ className?: string }>;
  tone?: "default" | "good" | "bad";
}) {
  return (
    <Card size="sm">
      <CardHeader>
        <CardDescription>{label}</CardDescription>
        <CardTitle className="text-2xl">{value}</CardTitle>
        <CardAction>
          <Icon
            className={
              tone === "good"
                ? "size-5 text-emerald-500"
                : tone === "bad"
                  ? "size-5 text-destructive"
                  : "size-5 text-muted-foreground"
            }
          />
        </CardAction>
      </CardHeader>
    </Card>
  );
}

function formatRunDate(iso: string): string {
  const d = new Date(iso);
  return d.toLocaleString(undefined, {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

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
  const maxCount = Math.max(...stages.map((s) => s.count), 1);

  return (
    <div className="flex flex-col gap-2">
      {stages.map((stage, i) => {
        const pct = (stage.count / maxCount) * 100;
        const prevCount = i > 0 ? stages[i - 1].count : null;
        const dropoff = prevCount != null ? prevCount - stage.count : 0;
        const dropoffPct = prevCount != null && prevCount > 0
          ? Math.round((dropoff / prevCount) * 100)
          : 0;
        const color = STAGE_COLORS[stage.tier] || "bg-primary/60";

        return (
          <div key={stage.label} className="flex flex-col gap-1">
            <div className="flex items-center justify-between text-sm">
              <span className="font-medium">{stage.label}</span>
              <div className="flex items-center gap-2">
                <span className="font-mono font-semibold">{stage.count}</span>
                {dropoff > 0 && (
                  <span className="text-xs text-muted-foreground">
                    −{dropoff} ({dropoffPct}%)
                  </span>
                )}
              </div>
            </div>
            <div className="h-7 w-full overflow-hidden rounded-md bg-muted/40">
              <div
                className={`flex h-full items-center justify-end rounded-md px-2 text-xs font-medium text-white transition-all ${color}`}
                style={{ width: `${Math.max(pct, 5)}%` }}
              >
                {stage.count > 0 && pct > 15 && stage.count}
              </div>
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
    (p) => p.enabled && (p.api_key_set || p.healthy === true) && p.models.length > 0,
  );
  const isProfileConfigured = settings?.profile_configured ?? false;
  const hasResume = resumeInfo?.exists ?? false;
  const setupComplete = hasProvider && isProfileConfigured && hasResume;

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

      {/* Funnel stats */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <StatCard label="Total Jobs" value={funnel?.total_jobs ?? 0} icon={Layers} />
        <StatCard label="Ready" value={funnel?.ready ?? 0} icon={CheckCircle2} tone="good" />
        <StatCard label="Rejected" value={funnel?.rejected ?? 0} icon={XCircle} tone="bad" />
        <StatCard
          label="JD Fetch Rate"
          value={jdFetchTotal > 0 ? `${jdFetchSuccess}/${jdFetchTotal} (${jdFetchPct}%)` : "—"}
          icon={FileSearch}
        />
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
          <CardContent>
            <FunnelChart stages={funnelStages} />
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
                    <span className="text-muted-foreground">{formatRunDate(run.started_at)}</span>
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
