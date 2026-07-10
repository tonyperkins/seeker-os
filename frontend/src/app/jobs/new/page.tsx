"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import Link from "next/link";
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  ExternalLink,
  AlertTriangle,
  Plus,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { api, type JobCreateResponse } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

type Phase = "idle" | "fetching" | "fetch_failed" | "success" | "exists" | "possible_dup" | "likely_dup" | "form";

export default function NewJobPage() {
  const { demoMode } = useDemoMode();
  const [phase, setPhase] = useState<Phase>("idle");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JobCreateResponse | null>(null);

  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [workplaceType] = useState("");
  const [seniorityLevel] = useState("");
  const [compMin] = useState("");
  const [compMax] = useState("");
  const [jdText, setJdText] = useState("");
  const [recruiterName, setRecruiterName] = useState("");
  const [recruiterEmail, setRecruiterEmail] = useState("");
  const [recruiterPhone, setRecruiterPhone] = useState("");
  const [recruiterLinkedin, setRecruiterLinkedin] = useState("");
  const [recruiterSource, setRecruiterSource] = useState("");
  const [recruiterAgency, setRecruiterAgency] = useState("");
  const [recruiterContactedAt, setRecruiterContactedAt] = useState("");

  const autoSubmitted = useRef(false);

  const handleSubmit = useCallback(async (force: boolean = false) => {
    if (!url.trim() && !jdText.trim()) {
      setError("Either a Job URL or JD Text is required");
      return;
    }

    setError(null);
    setPhase("fetching");

    try {
      const data: Parameters<typeof api.jobs.create>[0] = {};
      if (url.trim()) data.url = url.trim();
      if (title.trim()) data.title = title.trim();
      if (company.trim()) data.company = company.trim();
      if (location.trim()) data.location = location.trim();
      if (workplaceType.trim()) data.workplace_type = workplaceType.trim();
      if (seniorityLevel.trim()) data.seniority_level = seniorityLevel.trim();
      const cmin = parseInt(compMin, 10);
      if (!isNaN(cmin)) data.comp_min = cmin;
      const cmax = parseInt(compMax, 10);
      if (!isNaN(cmax)) data.comp_max = cmax;
      if (jdText.trim()) data.jd_text = jdText.trim();
      if (recruiterName.trim()) data.recruiter_name = recruiterName.trim();
      if (recruiterEmail.trim()) data.recruiter_email = recruiterEmail.trim();
      if (recruiterPhone.trim()) data.recruiter_phone = recruiterPhone.trim();
      if (recruiterLinkedin.trim()) data.recruiter_linkedin = recruiterLinkedin.trim();
      if (recruiterSource.trim()) data.recruiter_source = recruiterSource.trim();
      if (recruiterAgency.trim()) data.recruiter_agency = recruiterAgency.trim();
      if (recruiterContactedAt) data.recruiter_contacted_at = recruiterContactedAt;
      if (force) data.force = true;

      const response = await api.jobs.create(data);
      setResult(response);

      if (response.status === "created") {
        setPhase("success");
      } else if (response.status === "already_exists") {
        setPhase("exists");
      } else if (response.status === "possible_duplicate") {
        setPhase("possible_dup");
      } else if (response.status === "likely_duplicate") {
        setPhase("likely_dup");
      } else if (response.status === "fetch_failed") {
        setPhase("fetch_failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add job");
      setPhase("form");
    }
  }, [url, title, company, location, workplaceType, seniorityLevel, compMin, compMax, jdText, recruiterName, recruiterEmail, recruiterPhone, recruiterLinkedin, recruiterSource, recruiterAgency, recruiterContactedAt]);

  // Auto-submit when url param is present
  useEffect(() => {
    if (autoSubmitted.current) return;
    autoSubmitted.current = true;

    const params = new URLSearchParams(window.location.search);
    const urlParam = params.get("url");
    if (urlParam) {
      const titleParam = params.get("title") || "";
      const companyParam = params.get("company") || "";
      const locationParam = params.get("location") || "";
      // Hydrate bookmarklet data from the browser URL exactly once.
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setUrl(urlParam);
      if (titleParam) setTitle(titleParam);
      if (companyParam) setCompany(companyParam);
      if (locationParam) setLocation(locationParam);
      // Auto-submit with URL + any metadata extracted by bookmarklet
      setError(null);
      setPhase("fetching");
      const createData: Parameters<typeof api.jobs.create>[0] = { url: urlParam };
      if (titleParam) createData.title = titleParam;
      if (companyParam) createData.company = companyParam;
      if (locationParam) createData.location = locationParam;
      api.jobs
        .create(createData)
        .then((response) => {
          setResult(response);
          if (response.status === "created") setPhase("success");
          else if (response.status === "already_exists") setPhase("exists");
          else if (response.status === "possible_duplicate") setPhase("possible_dup");
          else if (response.status === "likely_duplicate") setPhase("likely_dup");
          else if (response.status === "fetch_failed") setPhase("fetch_failed");
        })
        .catch((err) => {
          setError(err instanceof Error ? err.message : "Failed to add job");
          setPhase("form");
        });
    } else {
      setPhase("form");
    }
  }, []);

  return (
    <div className="mx-auto max-w-2xl p-6">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-2xl font-bold tracking-tight">Add Job</h1>
        <Link href="/jobs">
          <Button variant="ghost" size="sm">Back to Jobs</Button>
        </Link>
      </div>

      {/* Loading */}
      {(phase === "idle" || phase === "fetching") && (
        <Card>
          <CardContent className="py-16">
            <div className="flex flex-col items-center gap-3">
              <Loader2 className="size-8 animate-spin text-muted-foreground" />
              <p className="text-sm text-muted-foreground">
                {phase === "fetching" ? "Fetching JD from URL…" : "Loading…"}
              </p>
              {url && (
                <p className="max-w-md truncate text-xs text-muted-foreground font-mono">
                  {url}
                </p>
              )}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Success */}
      {phase === "success" && result?.job && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <CheckCircle2 className="size-5 text-green-500" />
              Job Added
            </CardTitle>
            <CardDescription>The job has been scored and added to your pipeline.</CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4">
              <div className="rounded-lg border p-4">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-1">
                    <span className="font-medium">{result.job.title || "Untitled"}</span>
                    <span className="text-sm text-muted-foreground">{result.job.company || "Unknown company"}</span>
                  </div>
                  <div className="flex items-center gap-2">
                    <Badge variant="default">Score: {result.job.score ?? "—"}</Badge>
                    <Badge variant="secondary">ready</Badge>
                  </div>
                </div>
              </div>
              {result.filter_warnings.length > 0 && (
                <div className="flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 p-3 text-xs">
                  <div className="flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-500">
                    <AlertTriangle className="size-3.5" />
                    Filter Warnings (informational — not blocking)
                  </div>
                  {result.filter_warnings.map((w, i) => (
                    <span key={i} className="pl-5 text-amber-700 dark:text-amber-400">{w}</span>
                  ))}
                </div>
              )}
              <div className="flex gap-2">
                <Link href={`/jobs/${result.job.id}`}>
                  <Button>View Job</Button>
                </Link>
                <Link href="/jobs/new">
                  <Button variant="outline" onClick={() => { setPhase("form"); setUrl(""); setResult(null); setError(null); }}>
                    <Plus className="size-4" />
                    Add Another
                  </Button>
                </Link>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Already exists */}
      {phase === "exists" && result?.existing_job_id && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle className="size-5 text-amber-500" />
              Job Already Exists
            </CardTitle>
            <CardDescription>This job URL is already tracked in Seeker OS.</CardDescription>
          </CardHeader>
          <CardContent>
            <Link href={`/jobs/${result.existing_job_id}`}>
              <Button>
                <ExternalLink className="size-4" />
                View Existing Job
              </Button>
            </Link>
          </CardContent>
        </Card>
      )}

      {/* Possible duplicate */}
      {phase === "possible_dup" && result?.existing_job_id && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" />
              Possible Duplicate
            </CardTitle>
            <CardDescription>
              This job looks like one already tracked:{" "}
              <strong>{result.existing_summary ?? "Unknown"}</strong> — add anyway?
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-3">
              <Link href={`/jobs/${result.existing_job_id}`}>
                <Button variant="outline" size="sm">
                  <ExternalLink className="size-4" />
                  View Existing Job (#{result.existing_job_id})
                </Button>
              </Link>
              <div className="flex gap-2">
                <Link href="/jobs">
                  <Button variant="outline">Cancel</Button>
                </Link>
                <Button onClick={() => handleSubmit(true)}>
                  <AlertTriangle className="size-4" />
                  Add Anyway
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Likely duplicate */}
      {phase === "likely_dup" && result?.job && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" />
              Added (Possible Duplicate)
            </CardTitle>
            <CardDescription>
              This job looks similar to an existing one, but it was still added.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-3">
              <div className="rounded-lg border p-4">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-1">
                    <span className="font-medium">{result.job.title || "Untitled"}</span>
                    <span className="text-sm text-muted-foreground">{result.job.company || "Unknown company"}</span>
                  </div>
                  <Badge variant="default">Score: {result.job.score ?? "—"}</Badge>
                </div>
              </div>
              <div className="flex gap-2">
                <Link href={`/jobs/${result.job.id}`}>
                  <Button>View New Job</Button>
                </Link>
                {result.existing_job_id && (
                  <Link href={`/jobs/${result.existing_job_id}`}>
                    <Button variant="outline">
                      View Similar Job (#{result.existing_job_id})
                    </Button>
                  </Link>
                )}
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Fetch failed — show paste form */}
      {phase === "fetch_failed" && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2">
              <AlertCircle className="size-5 text-amber-500" />
              Couldn&apos;t Fetch the JD
            </CardTitle>
            <CardDescription>
              We couldn&apos;t fetch the job description from that URL. Paste the JD text below and we&apos;ll add the job.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4">
              {result?.fetch_error && (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-xs text-destructive">
                  <AlertCircle className="size-3.5 shrink-0" />
                  {result.fetch_error}
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="new-job-url">Job URL <span className="text-xs font-normal text-muted-foreground">(optional)</span></Label>
                <Input
                  id="new-job-url"
                  type="url"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="new-job-paste-jd">Paste JD Text</Label>
                <Textarea
                  id="new-job-paste-jd"
                  placeholder="Copy the job description from the posting and paste it here…"
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  className="min-h-[200px] font-mono text-xs"
                  autoFocus
                />
              </div>
              <div className="flex gap-2">
                <Button onClick={() => handleSubmit(false)} disabled={!jdText.trim() || demoMode}>
                  {demoMode ? "Demo mode" : "Add Job with Pasted JD"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Manual form (no url param) */}
      {phase === "form" && (
        <Card>
          <CardHeader>
            <CardTitle>Add Job Manually</CardTitle>
            <CardDescription>
              Paste a job URL and we&apos;ll fetch the JD, or paste the JD text directly if you don&apos;t have a link.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <div className="flex flex-col gap-4">
              {error && (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-3 text-sm text-destructive">
                  <AlertCircle className="size-4 shrink-0" />
                  {error}
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="manual-url">Job URL <span className="text-xs font-normal text-muted-foreground">(optional if JD text is provided)</span></Label>
                <Input
                  id="manual-url"
                  type="url"
                  placeholder="https://boards.greenhouse.io/company/jobs/123"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="manual-title">Title</Label>
                  <Input
                    id="manual-title"
                    placeholder="Senior SRE"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="manual-company">Company</Label>
                  <Input
                    id="manual-company"
                    placeholder="Acme Corp"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="manual-jd">JD Text <span className="text-xs font-normal text-muted-foreground">(paste the JD — no URL needed)</span></Label>
                <Textarea
                  id="manual-jd"
                  placeholder="Paste the full job description here. If no URL is provided, the job will be created from this text directly…"
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  className="min-h-[120px] font-mono text-xs"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-sm font-medium">Recruiter Contact <span className="text-xs font-normal text-muted-foreground">(optional)</span></Label>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-name" className="text-xs text-muted-foreground">Name</Label>
                    <Input
                      id="manual-recruiter-name"
                      placeholder="Jane Smith"
                      value={recruiterName}
                      onChange={(e) => setRecruiterName(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-source" className="text-xs text-muted-foreground">Source</Label>
                    <Input
                      id="manual-recruiter-source"
                      placeholder="LinkedIn, email, referral…"
                      value={recruiterSource}
                      onChange={(e) => setRecruiterSource(e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-agency" className="text-xs text-muted-foreground">Agency / Firm</Label>
                    <Input
                      id="manual-recruiter-agency"
                      placeholder="CyberCoders, Robert Half…"
                      value={recruiterAgency}
                      onChange={(e) => setRecruiterAgency(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-contacted-at" className="text-xs text-muted-foreground">Contacted At</Label>
                    <Input
                      id="manual-recruiter-contacted-at"
                      type="date"
                      value={recruiterContactedAt}
                      onChange={(e) => setRecruiterContactedAt(e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-email" className="text-xs text-muted-foreground">Email</Label>
                    <Input
                      id="manual-recruiter-email"
                      type="email"
                      placeholder="jane@company.com"
                      value={recruiterEmail}
                      onChange={(e) => setRecruiterEmail(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-phone" className="text-xs text-muted-foreground">Phone</Label>
                    <Input
                      id="manual-recruiter-phone"
                      placeholder="+1 555-123-4567"
                      value={recruiterPhone}
                      onChange={(e) => setRecruiterPhone(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="manual-recruiter-linkedin" className="text-xs text-muted-foreground">LinkedIn</Label>
                    <Input
                      id="manual-recruiter-linkedin"
                      placeholder="linkedin.com/in/janesmith"
                      value={recruiterLinkedin}
                      onChange={(e) => setRecruiterLinkedin(e.target.value)}
                    />
                  </div>
                </div>
              </div>
              <div className="flex gap-2">
                <Button onClick={() => handleSubmit(false)} disabled={(!url.trim() && !jdText.trim()) || demoMode}>
                  {demoMode ? "Demo mode" : url.trim() ? (jdText.trim() ? "Add Job" : "Fetch & Add") : "Add Job from JD"}
                </Button>
              </div>
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
