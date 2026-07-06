import Link from "next/link";
import { notFound } from "next/navigation";
import {
  ArrowLeft,
  Building2,
  Calendar,
  Cpu,
  FileText,
  FileDown,
  FileType,
  ShieldCheck,
  ShieldAlert,
  ShieldX,
  CheckCircle2,
  XCircle,
  Clock,
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
import { RevalidateButton } from "@/components/revalidate-button";
import { ResumeEditor } from "@/components/resume-editor";
import { DeleteResumeButton } from "@/components/delete-resume-button";
import { ClearExportsButton } from "@/components/clear-exports-button";
import { api, type ResumeDetail } from "@/lib/api";
import { formatDateTime } from "@/lib/date";

function severityVariant(severity: string) {
  switch (severity.toLowerCase()) {
    case "error":
    case "critical":
    case "high":
      return "destructive" as const;
    case "warning":
    case "medium":
      return "secondary" as const;
    default:
      return "outline" as const;
  }
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

export default async function ResumeDetailPage(props: PageProps<"/resumes/[id]">) {
  const { id } = await props.params;
  const numericId = Number(id);
  if (Number.isNaN(numericId)) notFound();

  let resume: ResumeDetail | null = null;
  let error: string | null = null;

  try {
    resume = await api.resumes.get(numericId);
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load resume";
  }

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <Link href="/resumes" className={buttonVariants({ variant: "ghost", size: "sm" }) + " w-fit"}>
          <ArrowLeft /> Back to resumes
        </Link>
        <Card>
          <CardContent className="py-10 text-center text-destructive">{error}</CardContent>
        </Card>
      </div>
    );
  }

  if (!resume) {
    notFound();
  }

  const totalTokens = resume.input_tokens + resume.output_tokens;
  const violations = resume.validation_violations ?? [];

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col gap-3">
        <Link href="/resumes" className={buttonVariants({ variant: "ghost", size: "sm" }) + " w-fit"}>
          <ArrowLeft /> Back to resumes
        </Link>
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="flex flex-col gap-1">
            <div className="flex items-center gap-2">
              <FileText className="size-5 text-muted-foreground" />
              <h1 className="text-2xl font-bold tracking-tight">
                {resume.job_title || `Resume #${resume.id}`}
              </h1>
            </div>
            <div className="flex flex-wrap items-center gap-2 text-muted-foreground">
              <Building2 className="size-4" />
              <span>{resume.job_company || "Unknown company"}</span>
              <Separator orientation="vertical" className="h-4" />
              <Link
                href={`/jobs/${resume.job_id}`}
                className="text-xs text-primary hover:underline"
              >
                View job #{resume.job_id}
              </Link>
            </div>
          </div>
          <div className="flex items-center gap-2">
            <Badge variant="outline">{resume.task}</Badge>
            {resume.validation_passed ? (
              <Badge variant="default" className="bg-emerald-600 text-white">
                <CheckCircle2 /> Validated
              </Badge>
            ) : (
              <Badge variant="destructive">
                <XCircle /> Validation failed
              </Badge>
            )}
            <DeleteResumeButton
              resumeId={resume.id}
              resumeLabel={resume.job_title || `Resume #${resume.id}`}
            />
          </div>
        </div>
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        {/* Left: metadata + downloads */}
        <div className="flex flex-col gap-4 lg:col-span-1">
          {/* Generation metadata */}
          <Card>
            <CardHeader>
              <CardTitle>Generation</CardTitle>
              <CardDescription>Model and usage details</CardDescription>
            </CardHeader>
            <CardContent className="flex flex-col gap-3">
              <InfoRow icon={Cpu} label="Provider" value={resume.provider} />
              <InfoRow icon={Cpu} label="Model" value={resume.model} />
              <Separator />
              <InfoRow icon={Clock} label="Latency" value={`${resume.latency_ms} ms`} />
              <InfoRow icon={Cpu} label="Input tokens" value={resume.input_tokens.toLocaleString()} />
              <InfoRow icon={Cpu} label="Output tokens" value={resume.output_tokens.toLocaleString()} />
              <InfoRow icon={Cpu} label="Total tokens" value={totalTokens.toLocaleString()} />
              <Separator />
              <InfoRow icon={Calendar} label="Generated" value={formatDateTime(resume.generated_at)} />
            </CardContent>
          </Card>

          {/* Downloads */}
          <Card>
            <CardHeader>
              <CardTitle>Downloads</CardTitle>
              <CardDescription>Export this resume</CardDescription>
              <CardAction>
                <ClearExportsButton resumeId={resume.id} />
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-2">
              <Button
                size="lg"
                nativeButton={false}
                render={
                  <a href={api.resumes.markdownUrl(resume.id)} target="_blank" rel="noopener noreferrer" />
                }
              >
                <FileText /> Markdown
              </Button>
              <Button
                size="lg"
                variant="outline"
                nativeButton={false}
                render={
                  <a href={api.resumes.pdfUrl(resume.id)} target="_blank" rel="noopener noreferrer" />
                }
              >
                <FileDown /> PDF
              </Button>
              <Button
                size="lg"
                variant="outline"
                nativeButton={false}
                render={
                  <a href={api.resumes.docxUrl(resume.id)} target="_blank" rel="noopener noreferrer" />
                }
              >
                <FileType /> DOCX
              </Button>
            </CardContent>
          </Card>

          {/* Link back to job */}
          <Button
            variant="secondary"
            nativeButton={false}
            render={<Link href={`/jobs/${resume.job_id}`} />}
          >
            <Building2 /> View job detail
          </Button>
        </div>

        {/* Right: validation + resume text */}
        <div className="flex flex-col gap-4 lg:col-span-2">
          {/* Validation status */}
          <Card>
            <CardHeader>
              <CardTitle>Validation</CardTitle>
              <CardDescription>
                Accuracy rules checked{resume.validation_checked_at ? ` · ${formatDateTime(resume.validation_checked_at)}` : ""}
              </CardDescription>
              <CardAction>
                <RevalidateButton resumeId={resume.id} />
              </CardAction>
            </CardHeader>
            <CardContent className="flex flex-col gap-4">
              <div className="flex items-center gap-2">
                {resume.validation_passed ? (
                  <>
                    <ShieldCheck className="size-5 text-emerald-600" />
                    <span className="text-sm font-medium">All accuracy rules passed</span>
                  </>
                ) : (
                  <>
                    <ShieldX className="size-5 text-destructive" />
                    <span className="text-sm font-medium">
                      {violations.length} violation{violations.length === 1 ? "" : "s"} found
                    </span>
                  </>
                )}
              </div>

              {violations.length > 0 && (
                <div className="flex flex-col gap-2">
                  {violations.map((v, i) => {
                    const severity = String(v.severity ?? v.level ?? "warning");
                    const rule = String(v.rule ?? v.rule_id ?? v.type ?? "unknown");
                    const message = String(v.message ?? v.description ?? v.detail ?? "");
                    return (
                      <div
                        key={i}
                        className="flex items-start gap-2.5 rounded-md border border-border p-3"
                      >
                        <ShieldAlert className="mt-0.5 size-4 shrink-0 text-amber-500" />
                        <div className="flex flex-col gap-1.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <Badge variant={severityVariant(severity)}>{severity}</Badge>
                            <span className="font-mono text-xs text-muted-foreground">{rule}</span>
                          </div>
                          {message && <p className="text-sm">{message}</p>}
                        </div>
                      </div>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          {/* Full resume text — preview + inline edit */}
          <ResumeEditor
            resumeId={resume.id}
            initialText={resume.resume_text || ""}
          />
        </div>
      </div>
    </div>
  );
}
