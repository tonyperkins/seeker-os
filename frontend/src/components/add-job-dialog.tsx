"use client";

import { useState } from "react";
import { Plus, Loader2, AlertCircle, CheckCircle2, ExternalLink, AlertTriangle } from "lucide-react";
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

type Phase = "form" | "fetching" | "fetch_failed" | "success" | "exists" | "likely_dup";

export function AddJobDialog({ onCreated }: { onCreated?: () => void }) {
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
    setPhase("form");
    setError(null);
    setResult(null);
  }

  function handleOpenChange(isOpen: boolean) {
    setOpen(isOpen);
    if (!isOpen) {
      resetForm();
    }
  }

  async function handleSubmit() {
    if (!url.trim()) {
      setError("URL is required");
      return;
    }

    setError(null);
    setPhase("fetching");

    try {
      const data: Parameters<typeof api.jobs.create>[0] = {
        url: url.trim(),
      };
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

      const response = await api.jobs.create(data);
      setResult(response);

      if (response.status === "created") {
        setPhase("success");
        onCreated?.();
      } else if (response.status === "already_exists") {
        setPhase("exists");
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

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <Button variant="default" size="sm">
            <Plus className="size-4" />
            Add Job
          </Button>
        }
      />
      <DialogContent className="sm:max-w-lg">
        {phase === "form" && (
          <>
            <DialogHeader>
              <DialogTitle>Add Job Manually</DialogTitle>
              <DialogDescription>
                Paste a job URL. We&apos;ll try to fetch the JD from the page. If that fails, you can paste the JD text directly.
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
                <Label htmlFor="add-job-url">Job URL *</Label>
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
                    className="h-9 rounded-lg border border-input bg-background px-3 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                  >
                    <option value="">—</option>
                    <option value="Remote">Remote</option>
                    <option value="Hybrid">Hybrid</option>
                    <option value="On-Site">On-Site</option>
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
                <Label htmlFor="add-job-jd">JD Text (optional — skip URL fetch)</Label>
                <Textarea
                  id="add-job-jd"
                  placeholder="Paste the full job description here to skip the URL fetch…"
                  value={jdText}
                  onChange={(e) => setJdText(e.target.value)}
                  className="min-h-[80px] font-mono text-xs"
                />
              </div>
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button onClick={handleSubmit} disabled={!url.trim()}>
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
                  className="min-h-[200px] font-mono text-xs"
                  autoFocus
                />
              </div>
            </div>
            <DialogFooter>
              <Button variant="outline" onClick={() => setPhase("form")}>
                Back
              </Button>
              <Button onClick={handleSubmit} disabled={!jdText.trim()}>
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
