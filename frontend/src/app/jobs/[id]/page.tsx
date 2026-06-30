import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  ExternalLink,
  MapPin,
  Briefcase,
  DollarSign,
  Building2,
  Layers,
  Calendar,
  GitCompare,
  CheckCircle2,
  XCircle,
  Pin,
  FileText,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { JobActions } from "@/components/job-actions";
import { AIPolicyToggle } from "@/components/ai-policy-toggle";
import { GenerateResumeButton } from "@/components/generate-resume-button";
import { JDRenderer } from "@/components/jd-renderer";
import { CompanyResearch } from "@/components/company-research";
import { ScoreBadges } from "@/components/score-badges";
import { JobAnalysis } from "@/components/job-analysis";
import { EventTimeline } from "@/components/event-timeline";
import { CopyButton } from "@/components/copy-button";
import { RunAllButton } from "@/components/run-all-button";
import { CopyAllButton } from "@/components/copy-all-button";
import { RefilterRescoreButton } from "@/components/refilter-rescore-button";
import { api, type JobDetail } from "@/lib/api";
import { formatDate } from "@/lib/date";

function formatComp(job: JobDetail): string {
  if (job.comp_min == null && job.comp_max == null) return "Not listed";
  const fmt = (n: number) => `$${(n / 1000).toFixed(0)}k`;
  if (job.comp_min != null && job.comp_max != null) {
    return `${fmt(job.comp_min)} – ${fmt(job.comp_max)}${job.comp_currency ? ` ${job.comp_currency}` : ""}`;
  }
  if (job.comp_min != null) return `${fmt(job.comp_min)}+`;
  return `≤${fmt(job.comp_max as number)}`;
}

function normalizeUrl(url: string): string {
  if (!url) return url;
  if (!/^https?:\/\//i.test(url)) return `https://${url}`;
  return url;
}

function formatDetailsText(job: JobDetail): string {
  const lines: string[] = [];
  lines.push(`Title: ${job.title}`);
  lines.push(`Company: ${job.company}`);
  lines.push(`Compensation: ${formatComp(job)}`);
  lines.push(`Location: ${job.location}`);
  lines.push(`Workplace: ${job.workplace_type}`);
  lines.push(`Seniority: ${job.seniority_level || "—"}`);
  lines.push(`Role type: ${job.role_type || "—"}`);
  lines.push(`Date posted: ${formatDate(job.date_posted)}`);
  lines.push(`Discovered: ${formatDate(job.discovered_at)}`);
  lines.push(`ATS source: ${job.ats_source || "—"}`);
  lines.push(`Commitment: ${job.commitment.join(", ") || "—"}`);
  lines.push(`Countries: ${job.workplace_countries.join(", ") || "—"}`);
  return lines.join("\n");
}

function formatScoreBreakdownText(job: JobDetail): string {
  const lines: string[] = [];
  lines.push(`Score: ${job.score != null ? job.score.toFixed(1) : "Not scored"}`);
  lines.push(`Tier: ${job.tier_passed} passed`);
  if (job.score_reasons.length > 0) {
    lines.push("\nReasons:");
    job.score_reasons.forEach(r => lines.push(`  + ${r}`));
  }
  if (job.score_gaps.length > 0) {
    lines.push("\nGaps:");
    job.score_gaps.forEach(g => lines.push(`  - ${g}`));
  }
  return lines.join("\n");
}

function formatRequirementsText(job: JobDetail): string {
  const lines: string[] = [];
  lines.push(job.requirements_summary || "(No requirements summary)");
  if (job.technical_tools.length > 0) {
    lines.push(`\nTools: ${job.technical_tools.join(", ")}`);
  }
  return lines.join("\n");
}

function InfoRow({
  icon: Icon,
  label,
  value,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-center gap-2.5 text-sm">
      <Icon className="size-4 text-muted-foreground" />
      <span className="text-muted-foreground">{label}</span>
      <span className="ml-auto font-medium text-right">{value || "—"}</span>
    </div>
  );
}

export const dynamic = "force-dynamic";

export default async function JobDetailPage(props: PageProps<"/jobs/[id]">) {
  const { id } = await props.params;
  const numericId = Number(id);
  if (Number.isNaN(numericId)) notFound();

  let job: JobDetail | null = null;
  let error: string | null = null;

  try {
    job = await api.jobs.get(numericId);
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load job";
  }

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <Link href="/jobs" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          <ArrowLeft /> Back to jobs
        </Link>
        <Card>
          <CardContent className="py-10 text-center text-destructive">{error}</CardContent>
        </Card>
      </div>
    );
  }

  if (!job) {
    notFound();
  }

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col gap-3">
        <Link href="/jobs" className={buttonVariants({ variant: "ghost", size: "sm" }) + " w-fit"}>
          <ArrowLeft /> Back to jobs
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              {job.is_pinned && <Pin className="size-4 text-amber-500" />}
              <h1 className="text-2xl font-bold tracking-tight">{job.title}</h1>
            </div>
            <div className="flex items-center gap-2 text-muted-foreground">
              <Building2 className="size-4" />
              <span>{job.company}</span>
              {job.company_homepage && (
                <a
                  href={normalizeUrl(job.company_homepage)}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-primary hover:underline"
                ><ExternalLink className="inline size-3" /></a>
              )}
            </div>
          </div>
          <ScoreBadges initialJob={job} />
        </div>
        <div className="flex flex-wrap gap-2">
          <RunAllButton jobId={job.id} />
          <CopyAllButton job={job} />
          <RefilterRescoreButton jobIds={[job.id]} />
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: info + actions */}
        <div className="flex flex-col gap-4 lg:col-span-1">
          <Card>
            <CardHeader>
              <div className="flex items-center justify-between">
                <div>
                  <CardTitle>Details</CardTitle>
                  <CardDescription>Structured job metadata</CardDescription>
                </div>
                <CopyButton text={formatDetailsText(job)} />
              </div>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <InfoRow icon={DollarSign} label="Compensation" value={formatComp(job)} />
              <InfoRow icon={MapPin} label="Location" value={job.location} />
              <InfoRow
                icon={Briefcase}
                label="Workplace"
                value={job.workplace_type}
              />
              <InfoRow icon={Layers} label="Seniority" value={job.seniority_level} />
              <InfoRow icon={Briefcase} label="Role type" value={job.role_type} />
              <InfoRow
                icon={Calendar}
                label="Date posted"
                value={formatDate(job.date_posted)}
              />
              <InfoRow icon={Calendar} label="Discovered" value={formatDate(job.discovered_at)} />
              <Separator />
              <InfoRow icon={Building2} label="ATS source" value={job.ats_source} />
              <InfoRow
                icon={Briefcase}
                label="Commitment"
                value={job.commitment.join(", ") || "—"}
              />
              <InfoRow
                icon={MapPin}
                label="Countries"
                value={job.workplace_countries.join(", ") || "—"}
              />
            </CardContent>
          </Card>

          {job.filter_warnings && job.filter_warnings.length > 0 && (
            <Card>
              <CardHeader>
                <CardTitle>Filter Warnings</CardTitle>
                <CardDescription>Informational — manual jobs bypass hard filters</CardDescription>
              </CardHeader>
              <CardContent>
                <ul className="flex flex-col gap-1.5 text-sm text-muted-foreground">
                  {job.filter_warnings.map((w, i) => (
                    <li key={i} className="flex items-start gap-2">
                      <XCircle className="mt-0.5 size-3.5 shrink-0 text-amber-500" />
                      <span>{w}</span>
                    </li>
                  ))}
                </ul>
              </CardContent>
            </Card>
          )}

          {job.overridden_at && (
            <Card>
              <CardHeader>
                <CardTitle>Override History</CardTitle>
                <CardDescription>This job was manually overridden</CardDescription>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <span className="text-muted-foreground">Overridden:</span>
                  <span className="font-medium">{formatDate(job.overridden_at)}</span>
                </div>
                {job.original_reject_reason && (
                  <div className="flex items-center gap-2">
                    <span className="text-muted-foreground">Original reason:</span>
                    <Badge variant="destructive">{job.original_reject_reason}</Badge>
                  </div>
                )}
                {job.override_note && (
                  <div className="flex flex-col gap-1">
                    <span className="text-muted-foreground">Note:</span>
                    <span className="rounded-md bg-muted p-2 text-xs">{job.override_note}</span>
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          <Card>
            <CardHeader>
              <CardTitle>Actions</CardTitle>
              <CardDescription>Update job status</CardDescription>
            </CardHeader>
            <CardContent>
              <JobActions jobId={job.id} currentStatus={job.status} />
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle>AI Policy</CardTitle>
              <CardDescription>Per-application AI generation override</CardDescription>
            </CardHeader>
            <CardContent>
              <AIPolicyToggle jobId={job.id} initialPolicy={job.ai_policy} />
            </CardContent>
          </Card>

          {job.apply_url && (
            <Button size="lg" nativeButton={false} render={
              <a href={job.apply_url} target="_blank" rel="noopener noreferrer" />
            }>
              <ExternalLink />
              Apply on {job.ats_source ?? "site"}
            </Button>
          )}

          <GenerateResumeButton jobId={job.id} />

          <Button
            size="lg"
            variant="outline"
            nativeButton={false}
            render={<Link href={`/resumes?job_id=${job.id}`} />}
          >
            <FileText />
            View Resumes
          </Button>
        </div>

        {/* Right: score breakdown + JD */}
        <div className="flex flex-col gap-4 lg:col-span-2">
          {/* Score breakdown */}
          <CollapsibleCard
            title="Score Breakdown"
            description={job.score != null ? `Score: ${job.score}` : "Not scored"}
            defaultOpen
            action={<CopyButton text={formatScoreBreakdownText(job)} />}
          >
            <div className="flex flex-col gap-4">
              <div className="flex flex-wrap items-center gap-2">
                <Badge variant="secondary">Tier {job.tier_passed} passed</Badge>
                {job.status === "rejected" && job.reject_reason && !job.reject_details && (
                  <Badge variant="destructive">{job.reject_reason}</Badge>
                )}
                {job.status === "rejected" && job.reject_details && job.reject_reason && (
                  <Badge variant="destructive" title={job.reject_details}>
                    {job.reject_reason}
                  </Badge>
                )}
              </div>
              {job.score_reasons.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <p className="text-xs font-medium text-muted-foreground">Reasons</p>
                  <div className="flex flex-col gap-1">
                    {job.score_reasons.map((reason, i) => (
                      <div key={i} className="flex items-start gap-2 text-sm">
                        <CheckCircle2 className="mt-0.5 size-3.5 shrink-0 text-emerald-500" />
                        <span>{reason}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {job.score_gaps.length > 0 && (
                <div className="flex flex-col gap-1.5">
                  <p className="text-xs font-medium text-muted-foreground">Gaps</p>
                  <div className="flex flex-col gap-1">
                    {job.score_gaps.map((gap, i) => (
                      <div key={i} className="flex items-start gap-2 text-sm">
                        <XCircle className="mt-0.5 size-3.5 shrink-0 text-destructive" />
                        <span>{gap}</span>
                      </div>
                    ))}
                  </div>
                </div>
              )}
              {job.score_reasons.length === 0 && job.score_gaps.length === 0 && (
                <p className="text-sm text-muted-foreground">
                  No score reasons or gaps recorded.
                </p>
              )}
            </div>
          </CollapsibleCard>

          {/* Cross-reference */}
          {job.cross_ref_status && (
            <CollapsibleCard
              title="Cross-Reference"
              description="Matched against application history"
            >
              <div className="flex flex-col gap-2 text-sm">
                <div className="flex items-center gap-2">
                  <Badge variant={job.cross_ref_status === "match" ? "default" : "outline"}>
                    {job.cross_ref_status}
                  </Badge>
                </div>
                <InfoRow
                  icon={GitCompare}
                  label="Status"
                  value={job.cross_ref_status}
                />
                <InfoRow
                  icon={Calendar}
                  label="Checked"
                  value={formatDate(job.cross_ref_date)}
                />
                {job.cross_ref_score != null && (
                  <InfoRow icon={GitCompare} label="Score" value={job.cross_ref_score} />
                )}
              </div>
            </CollapsibleCard>
          )}

          {/* AI Analysis */}
          <JobAnalysis jobId={job.id} />

          {/* Company Research */}
          <CompanyResearch jobId={job.id} />

          {/* Requirements summary */}
          {job.requirements_summary && (
            <CollapsibleCard
              title="Requirements Summary"
              action={<CopyButton text={formatRequirementsText(job)} />}
            >
              <div className="flex flex-col gap-3">
                <p className="text-sm text-muted-foreground">{job.requirements_summary}</p>
                {job.technical_tools.length > 0 && (
                  <div className="flex flex-wrap gap-1.5">
                    {job.technical_tools.map((tool) => (
                      <Badge key={tool} variant="outline" className="text-xs">
                        {tool}
                      </Badge>
                    ))}
                  </div>
                )}
              </div>
            </CollapsibleCard>
          )}

          {/* Full JD */}
          <CollapsibleCard
            title="Job Description"
            description={job.jd_fetch_status ? `Fetch: ${job.jd_fetch_status}` : "Full JD text"}
            contentClassName="p-0"
            action={<CopyButton text={job.jd_full || ""} />}
          >
            <ScrollArea className="h-[480px] rounded-md border border-border p-4">
              <JDRenderer content={job.jd_full || ""} />
            </ScrollArea>
          </CollapsibleCard>

          {/* Event Timeline */}
          <EventTimeline
            jobId={job.id}
            initialEvents={job.events}
            currentStatus={job.status}
            isStale={job.is_stale}
            daysSinceLastActivity={job.days_since_last_activity}
          />
        </div>
      </div>
    </div>
  );
}
