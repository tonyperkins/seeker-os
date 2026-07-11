"use client";

import { useState, useRef } from "react";
import Link from "next/link";
import { FileText, Loader2, CheckCircle2, XCircle, Sparkles, ShieldCheck, FileSearch, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { api, type ResumeProgressEvent } from "@/lib/api";
import { ErrorBanner } from "@/components/error-banner";
import { useDemoMode } from "@/lib/demo";

const STEPS = [
  { key: "load_job", label: "Loading job", icon: FileSearch },
  { key: "llm_generation", label: "Generating resume with LLM", icon: Sparkles },
  { key: "validation", label: "Running accuracy validation", icon: ShieldCheck },
  { key: "traceability", label: "Verifying claim traceability", icon: ShieldCheck },
  { key: "saving", label: "Saving resume", icon: Save },
] as const;

type StepStatus = "pending" | "started" | "completed";

export function GenerateResumeButton({
  jobId,
  size,
  variant,
}: {
  jobId: number;
  size?: "default" | "sm" | "lg" | "icon" | "icon-sm";
  variant?: "default" | "outline" | "ghost" | "destructive" | "link";
}) {
  const { demoMode } = useDemoMode();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ resume_id: number; validation_passed: boolean } | null>(null);
  const [open, setOpen] = useState(false);
  const [task, setTask] = useState("resume_generation_standard");
  const [events, setEvents] = useState<ResumeProgressEvent[]>([]);
  const abortRef = useRef<AbortController | null>(null);
  const [mode, setMode] = useState<"ai" | "manual">("ai");
  const [manualText, setManualText] = useState("");
  const [manualBusy, setManualBusy] = useState(false);

  async function saveManual() {
    if (!manualText.trim()) {
      setError("Paste your resume markdown before saving");
      return;
    }
    setManualBusy(true);
    setError(null);
    try {
      const res = await api.resumes.createManual(jobId, manualText);
      setResult(res);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Save failed");
    } finally {
      setManualBusy(false);
    }
  }

  async function generate() {
    setBusy(true);
    setError(null);
    setResult(null);
    setEvents([]);

    try {
      const { response, controller } = api.resumes.generateStream(jobId, task);
      abortRef.current = controller;

      const resp = await response;
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult: { resume_id: number; validation_passed: boolean } | null = null;
      let streamError: string | null = null;
      let currentEvent = "";

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (currentEvent === "done") {
              try {
                const parsed = JSON.parse(data) as Record<string, unknown>;
                finalResult = {
                  resume_id: parsed.resume_id as number,
                  validation_passed: parsed.validation_passed as boolean,
                };
              } catch {
                streamError = "Failed to parse generation response";
                break;
              }
            } else if (currentEvent === "error") {
              const parsed = JSON.parse(data);
              streamError = parsed.error;
            } else {
              const evt = JSON.parse(data) as ResumeProgressEvent;
              setEvents((prev) => {
                const filtered = prev.filter(
                  (e) => !(e.step === evt.step && e.status === evt.status),
                );
                return [...filtered, evt];
              });
            }
            currentEvent = "";
          }
        }
      }

      if (streamError) {
        setError(streamError);
      } else if (finalResult) {
        setResult(finalResult);
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  function handleOpenChange(nextOpen: boolean) {
    if (!nextOpen && busy && abortRef.current) {
      abortRef.current.abort();
    }
    setOpen(nextOpen);
    if (!nextOpen) {
      setEvents([]);
      setError(null);
      setResult(null);
      setMode("ai");
      setManualText("");
    }
  }

  // Build step statuses from events
  const stepStatuses: Record<string, StepStatus> = {};
  for (const step of STEPS) {
    const stepEvents = events.filter((e) => e.step === step.key);
    if (stepEvents.some((e) => e.status === "completed")) {
      stepStatuses[step.key] = "completed";
    } else if (stepEvents.some((e) => e.status === "started")) {
      stepStatuses[step.key] = "started";
    } else {
      stepStatuses[step.key] = "pending";
    }
  }

  const completedCount = Object.values(stepStatuses).filter((s) => s === "completed").length;
  const overallPct = Math.round((completedCount / STEPS.length) * 100);

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <Button size={size} variant={variant} disabled={busy || demoMode} title={demoMode ? "Resume generation is disabled in demo mode" : undefined}>
            {busy ? <Loader2 className="animate-spin" /> : <FileText />}
            {demoMode ? "Demo mode" : "Generate Resume"}
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{mode === "ai" ? "Generate tailored resume" : "Add a hand-built resume"}</DialogTitle>
          <DialogDescription>
            {mode === "ai"
              ? "This will use the LLM to tailor your master resume for this job. The result is validated against your accuracy rules."
              : "Paste the markdown for a resume you wrote yourself. It is saved as-is — no LLM generation or accuracy validation is run."}
          </DialogDescription>
        </DialogHeader>

        {!busy && !result && (
          <div className="flex gap-1 rounded-lg bg-muted p-1">
            <button
              type="button"
              onClick={() => setMode("ai")}
              className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === "ai" ? "bg-background shadow-sm" : "text-muted-foreground"
              }`}
            >
              Generate with AI
            </button>
            <button
              type="button"
              onClick={() => setMode("manual")}
              className={`flex-1 rounded-md px-3 py-1.5 text-sm font-medium transition-colors ${
                mode === "manual" ? "bg-background shadow-sm" : "text-muted-foreground"
              }`}
            >
              Paste my own
            </button>
          </div>
        )}

        {error && (
          <ErrorBanner message={error} />
        )}

        {busy && mode === "ai" && (
          <div className="flex flex-col gap-3 rounded-md border border-border p-4">
            {/* Overall progress bar */}
            <div className="flex flex-col gap-1">
              <div className="flex items-center justify-between text-xs">
                <span className="font-medium">Overall Progress</span>
                <span className="font-mono text-muted-foreground">{overallPct}%</span>
              </div>
              <div className="h-2 w-full overflow-hidden rounded-full bg-muted">
                <div
                  className="h-full rounded-full bg-primary transition-all duration-300"
                  style={{ width: `${overallPct}%` }}
                />
              </div>
            </div>

            {/* Step list */}
            <div className="flex flex-col gap-1.5">
              {STEPS.map((step) => {
                const status = stepStatuses[step.key];
                const Icon = step.icon;
                const stepEvents = events.filter((e) => e.step === step.key);
                const completedEvent = stepEvents.find((e) => e.status === "completed");

                return (
                  <div
                    key={step.key}
                    className={`flex items-center gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                      status === "started" ? "bg-primary/10" : ""
                    }`}
                  >
                    <div className="flex size-5 shrink-0 items-center justify-center">
                      {status === "completed" ? (
                        <CheckCircle2 className="size-4 text-emerald-500" />
                      ) : status === "started" ? (
                        <Loader2 className="size-4 animate-spin text-primary" />
                      ) : (
                        <Icon className="size-4 text-muted-foreground" />
                      )}
                    </div>
                    <span
                      className={`min-w-0 flex-1 leading-5 ${
                        status === "pending" ? "text-muted-foreground" : "font-medium"
                      }`}
                    >
                      {step.label}
                    </span>
                    {status === "completed" && completedEvent?.detail && (
                      <span className="max-w-[55%] shrink-0 text-right font-mono text-xs leading-5 text-muted-foreground">
                        {completedEvent.detail}
                      </span>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        )}

        {result ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm">
              {mode === "manual" ? (
                <><CheckCircle2 className="h-4 w-4 text-green-500" /> Resume saved</>
              ) : result.validation_passed ? (
                <><CheckCircle2 className="h-4 w-4 text-green-500" /> Resume generated and validated</>
              ) : (
                <><XCircle className="h-4 w-4 text-destructive" /> Resume generated with validation violations</>
              )}
            </div>
            <Button
              nativeButton={false}
              render={<Link href={`/resumes/${result.resume_id}`} />}
              onClick={() => setOpen(false)}
            >
              View resume →
            </Button>
          </div>
        ) : !busy && mode === "ai" ? (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">Model tier</label>
              <select
                value={task}
                onChange={(e) => setTask(e.target.value)}
                className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              >
                <option value="resume_generation_standard" className="bg-background text-foreground">Standard</option>
                <option value="resume_generation_high_value" className="bg-background text-foreground">High Value</option>
              </select>
            </div>
          </div>
        ) : !busy && mode === "manual" && (
          <div className="flex flex-col gap-1.5">
            <label className="text-sm font-medium">Resume markdown</label>
            <textarea
              value={manualText}
              onChange={(e) => setManualText(e.target.value)}
              placeholder="Paste your hand-built resume in markdown here…"
              rows={14}
              className="w-full rounded-lg border border-input bg-background px-3 py-2 text-sm font-mono text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
            />
          </div>
        )}

        <DialogFooter>
          {!result && (
            <>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              {mode === "ai" ? (
                <Button disabled={busy} onClick={generate}>
                  {busy ? <Loader2 className="animate-spin" /> : <FileText />}
                  Generate
                </Button>
              ) : (
                <Button disabled={manualBusy} onClick={saveManual}>
                  {manualBusy ? <Loader2 className="animate-spin" /> : <Save />}
                  Save
                </Button>
              )}
            </>
          )}
          {result && (
            <DialogClose render={<Button />}>Done</DialogClose>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
