"use client";

import { useState, useCallback, useRef } from "react";
import { useRouter } from "next/navigation";
import {
  Play,
  Loader2,
  CheckCircle2,
  AlertCircle,
  Search,
  Filter,
  FileSearch,
  Brain,
  Trophy,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { api, type PipelineRunSummary, type PipelineProgressEvent } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

const STEPS = [
  { key: "discovery", label: "Discovery", icon: Search },
  { key: "filtering", label: "Filtering", icon: Filter },
  { key: "jd_fetch", label: "JD Fetch", icon: FileSearch },
  { key: "scoring", label: "Scoring", icon: Brain },
  { key: "ranking", label: "Ranking", icon: Trophy },
] as const;

type StepStatus = "pending" | "started" | "in_progress" | "completed";

export function RunPipelineButton({ setupComplete = true, compact = false }: { setupComplete?: boolean; compact?: boolean }) {
  const { demoMode } = useDemoMode();
  const router = useRouter();
  const [loading, setLoading] = useState(false);
  const [result, setResult] = useState<PipelineRunSummary | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [events, setEvents] = useState<PipelineProgressEvent[]>([]);
  const [currentDetail, setCurrentDetail] = useState<string>("");
  const abortRef = useRef<AbortController | null>(null);

  const handleRun = useCallback(async () => {
    setLoading(true);
    setError(null);
    setResult(null);
    setEvents([]);
    setCurrentDetail("");

    try {
      const { response, controller } = api.pipeline.runStream({});
      abortRef.current = controller;

      const resp = await response;
      if (!resp.ok || !resp.body) {
        throw new Error(`HTTP ${resp.status}`);
      }

      const reader = resp.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let finalResult: PipelineRunSummary | null = null;
      let streamError: string | null = null;

      while (true) {
        const { done, value } = await reader.read();
        if (done) break;

        buffer += decoder.decode(value, { stream: true });
        const lines = buffer.split("\n");
        buffer = lines.pop() || "";

        let currentEvent = "";
        for (const line of lines) {
          if (line.startsWith("event: ")) {
            currentEvent = line.slice(7).trim();
          } else if (line.startsWith("data: ")) {
            const data = line.slice(6);
            if (currentEvent === "done") {
              try {
                finalResult = JSON.parse(data);
              } catch {
                streamError = "Failed to parse pipeline response";
                break;
              }
            } else if (currentEvent === "error") {
              const parsed = JSON.parse(data);
              streamError = parsed.error;
            } else {
              const evt = JSON.parse(data) as PipelineProgressEvent;
              setEvents((prev) => {
                // Replace previous event for same step+status, otherwise append
                const filtered = prev.filter(
                  (e) => !(e.step === evt.step && e.status === evt.status),
                );
                return [...filtered, evt];
              });
              setCurrentDetail(evt.detail);
            }
            currentEvent = "";
          }
        }
      }

      if (streamError) {
        setError(streamError);
      } else if (finalResult) {
        setResult(finalResult);
        // Refresh server-component data (jobs, funnel, pipeline runs) so
        // the dashboard reflects the new results without a manual reload.
        router.refresh();
      }
    } catch (err) {
      if (err instanceof Error && err.name === "AbortError") return;
      setError(err instanceof Error ? err.message : "Failed to run pipeline");
    } finally {
      setLoading(false);
    }
  }, [router]);

  // Build step statuses from events
  const stepStatuses: Record<string, StepStatus> = {};
  for (const step of STEPS) {
    const stepEvents = events.filter((e) => e.step === step.key);
    if (stepEvents.some((e) => e.status === "completed")) {
      stepStatuses[step.key] = "completed";
    } else if (stepEvents.some((e) => e.status === "in_progress")) {
      stepStatuses[step.key] = "in_progress";
    } else if (stepEvents.some((e) => e.status === "started")) {
      stepStatuses[step.key] = "started";
    } else {
      stepStatuses[step.key] = "pending";
    }
  }

  // Current active step
  const activeStep = STEPS.find((s) => {
    const st = stepStatuses[s.key];
    return st === "in_progress" || st === "started";
  });

  // Progress for current step
  const activeEvent = events
    .filter((e) => e.step === activeStep?.key && e.status === "in_progress")
    .pop();
  const progressPct =
    activeEvent && activeEvent.total > 0
      ? Math.round((activeEvent.current / activeEvent.total) * 100)
      : 0;

  // Overall progress (completed steps / total steps)
  const completedCount = Object.values(stepStatuses).filter((s) => s === "completed").length;
  const overallPct = Math.round((completedCount / STEPS.length) * 100);

  return (
    <div className="flex flex-col gap-3">
      <Button
        onClick={handleRun}
        disabled={loading || !setupComplete || demoMode}
        size={compact ? "default" : "lg"}
        title={demoMode ? "Pipeline runs are disabled in demo mode" : undefined}
      >
        {loading ? (
          <Loader2 className="animate-spin" />
        ) : (
          <Play />
        )}
        {loading ? "Running…" : demoMode ? "Demo mode" : setupComplete ? "Run pipeline" : "Complete setup first"}
      </Button>
      {!setupComplete && !compact && (
        <p className="text-xs text-muted-foreground text-center">
          Complete all setup steps above before running the pipeline.
        </p>
      )}

      {/* Progress display */}
      {loading && (
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
              const inProgressEvent = stepEvents.find((e) => e.status === "in_progress");

              return (
                <div
                  key={step.key}
                  className={`flex items-start gap-2 rounded-md px-2 py-1.5 text-sm transition-colors ${
                    status === "in_progress" || status === "started"
                      ? "bg-primary/10"
                      : ""
                  }`}
                >
                  <div className="flex size-5 shrink-0 items-center justify-center">
                    {status === "completed" ? (
                      <CheckCircle2 className="size-4 text-emerald-500" />
                    ) : status === "in_progress" || status === "started" ? (
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
                  {/* Step-specific progress — show completion detail once done,
                      otherwise the live in-progress count (never both). */}
                  {status === "completed" && completedEvent ? (
                    <span className="max-w-[55%] shrink-0 text-right font-mono text-xs leading-5 text-muted-foreground">
                      {completedEvent.detail}
                    </span>
                  ) : inProgressEvent && inProgressEvent.total > 0 ? (
                    <span className="shrink-0 font-mono text-xs leading-5 text-muted-foreground">
                      {inProgressEvent.current}/{inProgressEvent.total}
                    </span>
                  ) : null}
                </div>
              );
            })}
          </div>

          {/* Current detail line */}
          {currentDetail && (
            <div className="truncate border-t border-border pt-2 text-xs text-muted-foreground">
              {currentDetail}
            </div>
          )}

          {/* Step progress bar */}
          {activeEvent && activeEvent.total > 0 && (
            <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
              <div
                className="h-full rounded-full bg-primary/60 transition-all duration-300"
                style={{ width: `${progressPct}%` }}
              />
            </div>
          )}

          {/* Running counts */}
          <div className="grid grid-cols-3 gap-2 border-t border-border pt-2 text-center">
            <Count label="New" value={events.at(-1)?.cards_new ?? 0} />
            <Count label="JDs" value={events.at(-1)?.tier3_fetched ?? 0} />
            <Count label="Scored" value={events.at(-1)?.tier4_scored ?? 0} />
          </div>
        </div>
      )}

      {error && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {result && (
        <div className="flex items-start gap-2 rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-400">
          <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
          <div className="space-y-1">
            <p className="font-medium">Pipeline complete — run {result.run_id.slice(0, 8)}</p>
            <p className="text-xs text-muted-foreground">
              {result.cards_fetched} fetched · {result.cards_new} new · {result.tier2_passed} passed T2 ·{" "}
              {result.tier4_scored} scored · {result.tier5_ready} ready
            </p>
          </div>
        </div>
      )}
    </div>
  );
}

function Count({ label, value }: { label: string; value: number }) {
  return (
    <div className="flex flex-col">
      <span className="font-mono text-lg font-bold">{value}</span>
      <span className="text-xs text-muted-foreground">{label}</span>
    </div>
  );
}
