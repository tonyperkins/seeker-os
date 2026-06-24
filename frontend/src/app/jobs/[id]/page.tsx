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
  CardAction,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button, buttonVariants } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { ScrollArea } from "@/components/ui/scroll-area";
import { JobActions } from "@/components/job-actions";
import { GenerateResumeButton } from "@/components/generate-resume-button";
import { JDRenderer } from "@/components/jd-renderer";
import { api, type JobDetail } from "@/lib/api";

function formatComp(job: JobDetail): string {
  if (job.comp_min == null && job.comp_max == null) return "Not listed";
  const fmt = (n: number) => `$${(n / 1000).toFixed(0)}k`;
  if (job.comp_min != null && job.comp_max != null) {
    return `${fmt(job.comp_min)} – ${fmt(job.comp_max)}${job.comp_currency ? ` ${job.comp_currency}` : ""}`;
  }
  if (job.comp_min != null) return `${fmt(job.comp_min)}+`;
  return `≤${fmt(job.comp_max as number)}`;
}

function formatDate(iso: string | null): string {
  if (!iso) return "—";
  return new Date(iso).toLocaleDateString(undefined, {
    year: "numeric",
    month: "short",
    day: "numeric",
  });
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
                  href={job.company_homepage}
                  target="_blank"
                  rel="noopener noreferrer"
                  className="text-xs text-primary hover:underline"
                >
                  homepage <ExternalLink className="inline size-3" />
                </a>
              )}
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline">{job.status}</Badge>
            {job.score != null && (
              <Badge variant="default" className="text-base">Score: {job.score}</Badge>
            )}
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: info + actions */}
        <div className="flex flex-col gap-4 lg:col-span-1">
          <Card>
            <CardHeader>
              <CardTitle>Details</CardTitle>
              <CardDescription>Structured job metadata</CardDescription>
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

          <Card>
            <CardHeader>
              <CardTitle>Actions</CardTitle>
              <CardDescription>Update job status</CardDescription>
            </CardHeader>
            <CardContent>
              <JobActions jobId={job.id} currentStatus={job.status} />
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

          <Button
            size="lg"
            variant="outline"
            nativeButton={false}
            render={<Link href={`/resumes?job_id=${job.id}`} />}
          >
            <FileText />
            View Resumes
          </Button>

          <GenerateResumeButton jobId={job.id} />
        </div>

        {/* Right: score breakdown + JD */}
        <div className="flex flex-col gap-4 lg:col-span-2">
          {/* Score breakdown */}
          <Card>
            <CardHeader>
              <CardTitle>Score Breakdown</CardTitle>
              <CardDescription>
                {job.score != null ? `Score: ${job.score}` : "Not scored"}
              </CardDescription>
              <CardAction>
                <Badge variant="secondary">Tier {job.tier_passed} passed</Badge>
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
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
            </CardContent>
          </Card>

          {/* Cross-reference */}
          {job.cross_ref_status && (
            <Card>
              <CardHeader>
                <CardTitle>Cross-Reference</CardTitle>
                <CardDescription>Matched against application history</CardDescription>
                <CardAction>
                  <Badge variant={job.cross_ref_status === "match" ? "default" : "outline"}>
                    {job.cross_ref_status}
                  </Badge>
                </CardAction>
              </CardHeader>
              <CardContent className="flex flex-col gap-2 text-sm">
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
              </CardContent>
            </Card>
          )}

          {/* Requirements summary */}
          {job.requirements_summary && (
            <Card>
              <CardHeader>
                <CardTitle>Requirements Summary</CardTitle>
              </CardHeader>
              <CardContent>
                <p className="text-sm text-muted-foreground">{job.requirements_summary}</p>
                {job.technical_tools.length > 0 && (
                  <div className="mt-3 flex flex-wrap gap-1.5">
                    {job.technical_tools.map((tool) => (
                      <Badge key={tool} variant="outline" className="text-xs">
                        {tool}
                      </Badge>
                    ))}
                  </div>
                )}
              </CardContent>
            </Card>
          )}

          {/* Full JD */}
          <Card>
            <CardHeader>
              <CardTitle>Job Description</CardTitle>
              <CardDescription>
                {job.jd_fetch_status ? `Fetch: ${job.jd_fetch_status}` : "Full JD text"}
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ScrollArea className="h-[480px] rounded-md border border-border p-4">
                <JDRenderer content={job.jd_full || ""} />
              </ScrollArea>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}
