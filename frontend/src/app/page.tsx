import Link from "next/link";
import {
  TrendingUp,
  CheckCircle2,
  XCircle,
  Layers,
  Clock,
  ArrowRight,
  Trophy,
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
import { api, type FunnelStats, type PipelineRunRecord, type JobSummary } from "@/lib/api";

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

export default async function DashboardPage() {
  let funnel: FunnelStats | null = null;
  let runs: PipelineRunRecord[] = [];
  let topMatches: JobSummary[] = [];
  let error: string | null = null;

  try {
    [funnel, runs, topMatches] = await Promise.all([
      api.analytics.funnel(),
      api.pipeline.runs(),
      api.jobs.list({ status: "ready", limit: 5 }),
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

  const byTier = funnel?.by_tier ?? {};
  const tierEntries = Object.entries(byTier).sort((a, b) => a[0].localeCompare(b[0]));

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
        <StatCard label="Discovered" value={funnel?.discovered ?? 0} icon={TrendingUp} />
      </div>

      {/* By tier */}
      {tierEntries.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>By Tier</CardTitle>
            <CardDescription>Jobs surviving each pipeline tier</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-wrap gap-2">
              {tierEntries.map(([tier, count]) => (
                <Badge key={tier} variant="secondary" className="text-sm">
                  {tier}: {count}
                </Badge>
              ))}
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
