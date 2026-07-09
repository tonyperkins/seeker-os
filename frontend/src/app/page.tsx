import { redirect } from "next/navigation";
import { RunStrip } from "@/components/run-strip";
import { ActionQueue } from "@/components/action-queue";
import { MetricCards } from "@/components/metric-cards";
import { ActiveApplicationsContent, PipelineFunnel, Considering, StaleAlerts } from "@/components/dashboard-post-ready";
import { MovementFeedContent } from "@/components/movement-feed";
import { SignalQualityContent } from "@/components/signal-quality-card";
import { CollapsibleCard } from "@/components/collapsible-card";
import { SpendBreakdownCard } from "@/components/spend-breakdown-card";
import { api, type FunnelStats, type PipelineRunRecord, type JobSummary, type SettingsResponse, type MasterResumeInfo, type ProvidersConfigResponse, type MovementReport, type SignalQualityReport, type SpendReport } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function DashboardPage() {
  let funnel: FunnelStats | null = null;
  let runs: PipelineRunRecord[] = [];
  let actionQueueJobs: JobSummary[] = [];
  let activeJobs: JobSummary[] = [];
  let consideringJobs: JobSummary[] = [];
  let allPostReadyJobs: JobSummary[] = [];
  let settings: SettingsResponse | null = null;
  let resumeInfo: MasterResumeInfo | null = null;
  let providers: ProvidersConfigResponse | null = null;
  let isDemoMode = false;
  let docsToReview = 0;
  let movement: MovementReport | null = null;
  let signalQuality: SignalQualityReport | null = null;
  let spend: SpendReport | null = null;
  let error: string | null = null;

  try {
    const [activeResp, consideringResp, allPostReadyResp, actionQueueResp] = await Promise.all([
      api.jobs.list({ status: "applied,engaged,offer_accepted,offer_declined,company_rejected,withdrawn", limit: 50 }),
      api.jobs.list({ status: "reviewing,interested", limit: 50 }),
      api.jobs.list({ status: "reviewing,interested,applied,engaged,offer_accepted,offer_declined,company_rejected,withdrawn", limit: 100 }),
      api.jobs.list({ status: "ready", sort_by: "net_score", limit: 5 }),
    ]);

    [funnel, runs, settings, resumeInfo, providers, { demo_mode: isDemoMode }, { count: docsToReview }, movement, signalQuality, spend] = await Promise.all([
      api.analytics.funnel(),
      api.pipeline.runs(),
      api.settings.get(),
      api.resumes.getMaster().catch(() => null),
      api.models.getConfig().catch(() => null),
      api.demoMode.get().catch(() => ({ demo_mode: false })),
      api.resumes.pendingCount().catch(() => ({ count: 0 })),
      api.analytics.movement({ days: 7, limit: 30 }).catch(() => null),
      api.analytics.signalQuality().catch(() => null),
      api.analytics.spend().catch(() => null),
    ]);
    actionQueueJobs = actionQueueResp.jobs ?? [];
    activeJobs = activeResp.jobs ?? [];
    consideringJobs = consideringResp.jobs ?? [];
    allPostReadyJobs = allPostReadyResp.jobs ?? [];
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load dashboard data";
  }

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
        <div className="rounded-lg bg-card p-6 text-center text-destructive ring-1 ring-foreground/10">
          {error}
        </div>
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

  // Demo mode ships with a synthetic profile, resume, and zero providers.
  // It should land directly on the dashboard, not the onboarding wizard.
  if (!setupComplete && !isDemoMode) {
    redirect("/onboarding");
  }

  const funnelStages = funnel?.funnel ?? [];
  const jdFetchTotal = funnel?.jd_fetch_total ?? 0;
  const jdFetchSuccess = funnel?.jd_fetch_success ?? 0;
  const jdFetchPct = jdFetchTotal > 0 ? Math.round((jdFetchSuccess / jdFetchTotal) * 100) : 0;

  const lastRun = runs.length > 0 ? runs[0] : null;

  const needsDecision = funnel?.ready ?? 0;
  const awaitingReply = (funnel?.by_status?.applied ?? 0) + (funnel?.by_status?.engaged ?? 0);

  return (
    <div className="flex flex-col gap-6">
      {/* Page header */}
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Dashboard</h1>
      </div>

      {/* ZONE 1 — Ops strip (with expandable run history + funnel) */}
      <RunStrip
        lastRun={lastRun ? {
          started_at: lastRun.started_at,
          cards_new: lastRun.cards_new,
          jobs_ready: lastRun.jobs_ready,
        } : null}
        jdFetchPct={jdFetchPct}
        jdFetchTotal={jdFetchTotal}
        jdFetchSuccess={jdFetchSuccess}
        runs={runs}
        funnelStages={funnelStages}
        rejectedCount={funnel?.rejected ?? 0}
      />

      {/* ZONE 2 — Metric cards */}
      <MetricCards data={{
        needsDecision,
        docsToReview,
        awaitingReply,
        costPerReady: spend?.cost_per_ready ?? null,
        pricingConfigured: spend?.pricing_configured ?? false,
      }} />

      {/* ZONE 3 — Action queue (hero) */}
      <ActionQueue jobs={actionQueueJobs} />

      {/* ZONE 4 — Active Applications + Movement (side by side) */}
      <CollapsibleCard
        title="Applications & Movement"
        description="Active applications and recent status changes"
        storageKey="dash-apps-movement"
        contentClassName="grid gap-4 lg:grid-cols-2"
      >
        <div className="flex flex-col gap-2 min-h-0">
          <h4 className="text-sm font-semibold text-muted-foreground">Active Applications</h4>
          <ActiveApplicationsContent jobs={activeJobs} />
        </div>
        <div className="flex flex-col gap-2 min-h-0 border-l border-border pl-4">
          <h4 className="text-sm font-semibold text-muted-foreground">Movement</h4>
          {movement && (movement.events.length > 0 || movement.rejection_count > 0) ? (
            <MovementFeedContent
              events={movement.events}
              rejectionCount={movement.rejection_count}
              rejectionBreakdown={movement.rejection_breakdown}
            />
          ) : (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No status changes in the last 7 days.
            </p>
          )}
        </div>
      </CollapsibleCard>

      {/* ZONE 5 — Signal Quality + Pipeline (side by side) */}
      <CollapsibleCard
        title="Signal & Pipeline"
        description="AI verdict quality and post-ready pipeline funnel"
        storageKey="dash-signal-pipeline"
        contentClassName="grid gap-4 lg:grid-cols-2"
      >
        <div className="flex flex-col gap-4 min-h-0">
          <h4 className="text-sm font-semibold text-muted-foreground">Signal Quality</h4>
          <SignalQualityContent report={signalQuality} />
        </div>
        <div className="flex flex-col gap-3 min-h-0 border-l border-border pl-4">
          <h4 className="text-sm font-semibold text-muted-foreground">Pipeline</h4>
          <PipelineFunnel byStatus={funnel?.by_status ?? {}} />
        </div>
      </CollapsibleCard>

      {/* ZONE 6 — Considering + Stale Alerts */}
      <div className="grid gap-4 lg:grid-cols-2">
        <Considering jobs={consideringJobs} />
        <StaleAlerts jobs={allPostReadyJobs} />
      </div>

      {/* ZONE 7 — LLM Spend */}
      <SpendBreakdownCard report={spend} />
    </div>
  );
}
