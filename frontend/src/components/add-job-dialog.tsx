"use client";

import { useState } from "react";
import { Plus, Loader2, AlertCircle, CheckCircle2, ExternalLink, AlertTriangle, Send, Users, XCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { api, type JobCreateResponse } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

type Phase = "form" | "fetching" | "fetch_failed" | "success" | "exists" | "possible_dup" | "likely_dup";

type CleanStartTarget = "applied" | "engaged" | "company_rejected";

function defaultDateTimeLocal(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function toISOString(localDateTime: string): string {
  if (!localDateTime) return new Date().toISOString();
  const dt = new Date(localDateTime);
  return dt.toISOString();
}

export function AddJobDialog({ onCreated }: { onCreated?: () => void }) {
  const { demoMode } = useDemoMode();
  const [open, setOpen] = useState(false);
  const [phase, setPhase] = useState<Phase>("form");
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<JobCreateResponse | null>(null);

  // Form fields
  const [url, setUrl] = useState("");
  const [title, setTitle] = useState("");
  const [company, setCompany] = useState("");
  const [location, setLocation] = useState("");
  const [workplaceType, setWorkplaceType] = useState("");
  const [seniorityLevel, setSeniorityLevel] = useState("");
  const [compMin, setCompMin] = useState("");
  const [compMax, setCompMax] = useState("");
  const [jdText, setJdText] = useState("");
  const [recruiterName, setRecruiterName] = useState("");
  const [recruiterEmail, setRecruiterEmail] = useState("");
  const [recruiterPhone, setRecruiterPhone] = useState("");
  const [recruiterLinkedin, setRecruiterLinkedin] = useState("");
  const [recruiterSource, setRecruiterSource] = useState("");
  const [recruiterAgency, setRecruiterAgency] = useState("");
  const [recruiterContactedAt, setRecruiterContactedAt] = useState("");

  // Clean-start state (for "I already applied" handoff from success phase)
  const [showCleanStart, setShowCleanStart] = useState(false);
  const [cleanStartBusy, setCleanStartBusy] = useState<string | null>(null);
  const [cleanStartError, setCleanStartError] = useState<string | null>(null);
  const [csDate, setCsDate] = useState(defaultDateTimeLocal());
  const [csAppliedDate, setCsAppliedDate] = useState("");
  const [csNote, setCsNote] = useState("");

  function resetForm() {
    setUrl("");
    setTitle("");
    setCompany("");
    setLocation("");
    setWorkplaceType("");
    setSeniorityLevel("");
    setCompMin("");
    setCompMax("");
    setJdText("");
    setRecruiterName("");
    setRecruiterEmail("");
    setRecruiterPhone("");
    setRecruiterLinkedin("");
    setRecruiterSource("");
    setRecruiterAgency("");
    setRecruiterContactedAt("");
    setPhase("form");
    setError(null);
    setResult(null);
    setShowCleanStart(false);
    setCleanStartError(null);
    setCsDate(defaultDateTimeLocal());
    setCsAppliedDate("");
    setCsNote("");
  }

  function handleOpenChange(isOpen: boolean) {
    setOpen(isOpen);
    if (!isOpen) {
      resetForm();
    }
  }

  async function handleSubmit(force: boolean = false) {
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
        onCreated?.();
      } else if (response.status === "already_exists") {
        setPhase("exists");
      } else if (response.status === "possible_duplicate") {
        setPhase("possible_dup");
      } else if (response.status === "likely_duplicate") {
        setPhase("likely_dup");
        onCreated?.();
      } else if (response.status === "fetch_failed") {
        setPhase("fetch_failed");
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add job");
      setPhase("form");
    }
  }

  async function doCleanStart(target: CleanStartTarget) {
    if (!result?.job) return;
    setCleanStartBusy(`clean-start-${target}`);
    setCleanStartError(null);
    try {
      await api.jobs.cleanStart(result.job.id, target, {
        occurred_at: toISOString(csDate),
        applied_occurred_at: csAppliedDate ? toISOString(csAppliedDate) : undefined,
        note: csNote.trim() || undefined,
      });
      onCreated?.();
      window.open(`/jobs/${result.job.id}`, "_self");
    } catch (err) {
      setCleanStartError(err instanceof Error ? err.message : "Clean-start failed");
    } finally {
      setCleanStartBusy(null);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <Button variant="default" size="sm" disabled={demoMode} title={demoMode ? "Adding jobs is disabled in demo mode" : undefined}>
            <Plus className="size-4" />
            {demoMode ? "Demo mode" : "Add Job"}
          </Button>
        }
      />
      <DialogContent className="sm:max-w-lg">
        {phase === "form" && (
          <>
            <DialogHeader>
              <DialogTitle>Add Job Manually</DialogTitle>
              <DialogDescription>
                Paste a job URL and we&apos;ll fetch the JD, or paste the JD text directly if you don&apos;t have a link.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              {error && (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-sm text-destructive">
                  <AlertCircle className="size-4 shrink-0" />
                  {error}
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="add-job-url">Job URL <span className="text-xs font-normal text-muted-foreground">(optional if JD text is provided)</span></Label>
                <Input
                  id="add-job-url"
                  type="url"
                  placeholder="https://boards.greenhouse.io/company/jobs/123"
                  value={url}
                  onChange={(e) => setUrl(e.target.value)}
                />
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="add-job-title">Title</Label>
                  <Input
                    id="add-job-title"
                    placeholder="Senior SRE"
                    value={title}
                    onChange={(e) => setTitle(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="add-job-company">Company</Label>
                  <Input
                    id="add-job-company"
                    placeholder="Acme Corp"
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                  />
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="add-job-location">Location</Label>
                  <Input
                    id="add-job-location"
                    placeholder="Remote, US"
                    value={location}
                    onChange={(e) => setLocation(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="add-job-workplace">Workplace Type</Label>
                  <select
                    id="add-job-workplace"
                    value={workplaceType}
                    onChange={(e) => setWorkplaceType(e.target.value)}
                    className="h-9 rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  >
                    <option value="" className="bg-background text-foreground">—</option>
                    <option value="Remote" className="bg-background text-foreground">Remote</option>
                    <option value="Hybrid" className="bg-background text-foreground">Hybrid</option>
                    <option value="On-Site" className="bg-background text-foreground">On-Site</option>
                  </select>
                </div>
              </div>
              <div className="grid grid-cols-2 gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="add-job-comp-min">Comp Min ($)</Label>
                  <Input
                    id="add-job-comp-min"
                    type="number"
                    placeholder="160000"
                    value={compMin}
                    onChange={(e) => setCompMin(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="add-job-comp-max">Comp Max ($)</Label>
                  <Input
                    id="add-job-comp-max"
                    type="number"
                    placeholder="200000"
                    value={compMax}
                    onChange={(e) => setCompMax(e.target.value)}
                  />
                </div>
              </div>
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="add-job-jd">JD Text <span className="text-xs font-normal text-muted-foreground">(paste the JD — no URL needed)</span></Label>
                <Textarea
                  id="add-job-jd"
                  placeholder="Paste the full job description here. If no URL is provided, the job will be created from this text directly…"
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  className="max-h-[200px] min-h-[80px] font-mono text-xs"
                />
              </div>
              <div className="flex flex-col gap-1.5">
                <Label className="text-sm font-medium">Recruiter Contact <span className="text-xs font-normal text-muted-foreground">(optional)</span></Label>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-name" className="text-xs text-muted-foreground">Name</Label>
                    <Input
                      id="add-job-recruiter-name"
                      placeholder="Jane Smith"
                      value={recruiterName}
                      onChange={(e) => setRecruiterName(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-source" className="text-xs text-muted-foreground">Source</Label>
                    <Input
                      id="add-job-recruiter-source"
                      placeholder="LinkedIn, email, referral…"
                      value={recruiterSource}
                      onChange={(e) => setRecruiterSource(e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-2 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-agency" className="text-xs text-muted-foreground">Agency / Firm</Label>
                    <Input
                      id="add-job-recruiter-agency"
                      placeholder="CyberCoders, Robert Half…"
                      value={recruiterAgency}
                      onChange={(e) => setRecruiterAgency(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-contacted-at" className="text-xs text-muted-foreground">Contacted At</Label>
                    <Input
                      id="add-job-recruiter-contacted-at"
                      type="date"
                      value={recruiterContactedAt}
                      onChange={(e) => setRecruiterContactedAt(e.target.value)}
                    />
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-email" className="text-xs text-muted-foreground">Email</Label>
                    <Input
                      id="add-job-recruiter-email"
                      type="email"
                      placeholder="jane@company.com"
                      value={recruiterEmail}
                      onChange={(e) => setRecruiterEmail(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-phone" className="text-xs text-muted-foreground">Phone</Label>
                    <Input
                      id="add-job-recruiter-phone"
                      placeholder="+1 555-123-4567"
                      value={recruiterPhone}
                      onChange={(e) => setRecruiterPhone(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="add-job-recruiter-linkedin" className="text-xs text-muted-foreground">LinkedIn</Label>
                    <Input
                      id="add-job-recruiter-linkedin"
                      placeholder="linkedin.com/in/janesmith"
                      value={recruiterLinkedin}
                      onChange={(e) => setRecruiterLinkedin(e.target.value)}
                    />
                  </div>
                </div>
              </div>
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button onClick={() => handleSubmit(false)} disabled={(!url.trim() && !jdText.trim())}>
                {jdText.trim() ? "Add Job" : "Fetch & Add"}
              </Button>
            </DialogFooter>
          </>
        )}

        {phase === "fetching" && (
          <div className="flex flex-col items-center gap-3 py-8">
            <Loader2 className="size-8 animate-spin text-muted-foreground" />
            <p className="text-sm text-muted-foreground">
              {jdText.trim() ? "Inserting and scoring job…" : "Fetching JD from URL…"}
            </p>
          </div>
        )}

        {phase === "fetch_failed" && (
          <>
            <DialogHeader>
              <DialogTitle>Couldn&apos;t Fetch the JD</DialogTitle>
              <DialogDescription>
                We couldn&apos;t fetch the job description from that URL. Paste the JD text below and we&apos;ll add the job with your provided details.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              {result?.fetch_error && (
                <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
                  <AlertCircle className="size-3.5 shrink-0" />
                  {result.fetch_error}
                </div>
              )}
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="add-job-paste-jd">Paste JD Text</Label>
                <Textarea
                  id="add-job-paste-jd"
                  placeholder="Copy the job description from the posting and paste it here…"
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  className="max-h-[300px] min-h-[200px] font-mono text-xs"
                  autoFocus
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setPhase("form")}>
                Back
              </Button>
              <Button onClick={() => handleSubmit(false)} disabled={!jdText.trim()}>
                Add Job with Pasted JD
              </Button>
            </DialogFooter>
          </>
        )}

        {phase === "success" && result?.job && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <CheckCircle2 className="size-5 text-green-500" />
                Job Added
              </DialogTitle>
              <DialogDescription>
                The job has been scored and added to your pipeline.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="rounded-lg border p-3">
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
                <div className="flex flex-col gap-1 rounded-lg border border-amber-500/30 bg-amber-500/10 p-2 text-xs">
                  <div className="flex items-center gap-1.5 font-medium text-amber-600 dark:text-amber-500">
                    <AlertTriangle className="size-3.5" />
                    Filter Warnings (informational — not blocking)
                  </div>
                  {result.filter_warnings.map((w, i) => (
                    <span key={i} className="pl-5 text-amber-700 dark:text-amber-400">{w}</span>
                  ))}
                </div>
              )}
              {!showCleanStart && (
                <Button variant="outline" size="sm" onClick={() => setShowCleanStart(true)}>
                  <Send className="size-4" />
                  I already applied to this
                </Button>
              )}
              {showCleanStart && (
                <div className="flex flex-col gap-3 rounded-lg border p-3">
                  <div className="flex items-center gap-1.5 text-sm font-medium">
                    <Send className="size-4" />
                    Clean-start (already applied?)
                  </div>
                  {cleanStartError && (
                    <div className="flex items-center gap-2 rounded-lg border border-destructive/30 bg-destructive/10 p-2 text-xs text-destructive">
                      <AlertCircle className="size-3.5 shrink-0" />
                      {cleanStartError}
                    </div>
                  )}
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cs-date">Date / Time</Label>
                    <Input
                      id="cs-date"
                      type="datetime-local"
                      value={csDate}
                      onChange={(e) => setCsDate(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Set to the real date the event occurred. Defaults to now.
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cs-applied-date">
                      Applied Date <span className="text-xs font-normal text-muted-foreground">(optional — leave blank if unknown)</span>
                    </Label>
                    <Input
                      id="cs-applied-date"
                      type="datetime-local"
                      value={csAppliedDate}
                      onChange={(e) => setCsAppliedDate(e.target.value)}
                    />
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="cs-note">
                      Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                    </Label>
                    <Textarea
                      id="cs-note"
                      value={csNote}
                      onChange={(e) => setCsNote(e.target.value)}
                      rows={2}
                      className="text-sm"
                    />
                  </div>
                  <div className="flex flex-wrap gap-2">
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => doCleanStart("applied")}
                      disabled={cleanStartBusy !== null}
                    >
                      {cleanStartBusy === "clean-start-applied" ? <Loader2 className="size-3.5 animate-spin" /> : <Send className="size-3.5" />}
                      Applied
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => doCleanStart("engaged")}
                      disabled={cleanStartBusy !== null}
                    >
                      {cleanStartBusy === "clean-start-engaged" ? <Loader2 className="size-3.5 animate-spin" /> : <Users className="size-3.5" />}
                      Engaged
                    </Button>
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={() => doCleanStart("company_rejected")}
                      disabled={cleanStartBusy !== null}
                    >
                      {cleanStartBusy === "clean-start-company_rejected" ? <Loader2 className="size-3.5 animate-spin" /> : <XCircle className="size-3.5" />}
                      Company Rejected
                    </Button>
                  </div>
                </div>
              )}
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
              <Button onClick={() => window.open(`/jobs/${result.job!.id}`, "_self")}>
                View Job
              </Button>
            </DialogFooter>
          </>
        )}

        {phase === "exists" && result?.existing_job_id && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <AlertCircle className="size-5 text-amber-500" />
                Job Already Exists
              </DialogTitle>
              <DialogDescription>
                This job URL is already tracked in Seeker OS.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
              <Button onClick={() => window.open(`/jobs/${result.existing_job_id}`, "_self")}>
                <ExternalLink className="size-4" />
                View Existing Job
              </Button>
            </DialogFooter>
          </>
        )}

        {phase === "possible_dup" && result?.existing_job_id && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <AlertTriangle className="size-5 text-amber-500" />
                Possible Duplicate
              </DialogTitle>
              <DialogDescription>
                This job looks like one already tracked in Seeker OS:{" "}
                <strong>{result.existing_summary ?? "Unknown"}</strong>
                {" "}— add anyway?
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <Button
                variant="outline"
                size="sm"
                onClick={() => window.open(`/jobs/${result.existing_job_id}`, "_self")}
              >
                <ExternalLink className="size-4" />
                View Existing Job (#{result.existing_job_id})
              </Button>
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button variant="default" onClick={() => handleSubmit(true)}>
                <AlertTriangle className="size-4" />
                Add Anyway
              </Button>
            </DialogFooter>
          </>
        )}

        {phase === "likely_dup" && result?.job && (
          <>
            <DialogHeader>
              <DialogTitle className="flex items-center gap-2">
                <AlertTriangle className="size-5 text-amber-500" />
                Possible Duplicate
              </DialogTitle>
              <DialogDescription>
                This job looks similar to an existing one, but it was still added. Review both to confirm they&apos;re different.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-2">
              <div className="rounded-lg border p-3">
                <div className="flex items-center justify-between">
                  <div className="flex flex-col gap-1">
                    <span className="font-medium">{result.job.title || "Untitled"}</span>
                    <span className="text-sm text-muted-foreground">{result.job.company || "Unknown company"}</span>
                  </div>
                  <Badge variant="default">Score: {result.job.score ?? "—"}</Badge>
                </div>
              </div>
              {result.existing_job_id && (
                <Button
                  variant="outline"
                  size="sm"
                  onClick={() => window.open(`/jobs/${result.existing_job_id}`, "_self")}
                >
                  <ExternalLink className="size-4" />
                  View Similar Job (#{result.existing_job_id})
                </Button>
              )}
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Close</DialogClose>
              <Button onClick={() => window.open(`/jobs/${result.job!.id}`, "_self")}>
                View New Job
              </Button>
            </DialogFooter>
          </>
        )}
      </DialogContent>
    </Dialog>
  );
}
