"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, MinusCircle } from "lucide-react";
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
import { Textarea } from "@/components/ui/textarea";
import { api, type SkipReasonOption, type NoReasonSkip } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

export function BulkAnnotateSkips() {
  const { demoMode } = useDemoMode();
  const [open, setOpen] = useState(false);
  const [skips, setSkips] = useState<NoReasonSkip[] | null>(null);
  const [skipReasons, setSkipReasons] = useState<SkipReasonOption[]>([]);
  const [annotating, setAnnotating] = useState<number | null>(null);
  const [selectedReason, setSelectedReason] = useState<Record<number, string>>({});
  const [details, setDetails] = useState<Record<number, string>>({});
  const [error, setError] = useState<string | null>(null);
  const [done, setDone] = useState<Set<number>>(new Set());

  const fetchSkips = useCallback(async () => {
    try {
      const data = await api.jobs.listNoReasonSkips();
      setSkips(data);
      setDone(new Set());
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load skips");
      setSkips([]);
    }
  }, []);

  useEffect(() => {
    if (open) {
      fetchSkips();
      api.settings.get().then((s) => {
        if (s.skip_reasons?.length) setSkipReasons(s.skip_reasons);
      }).catch(() => {});
    }
  }, [open, fetchSkips]);

  const reasonHint = (key: string): string => {
    const r = skipReasons.find((sr) => sr.key === key);
    return r?.hint || "What specifically about this job doesn't fit?";
  };

  async function annotate(jobId: number) {
    const reason = selectedReason[jobId];
    if (!reason) return;
    setAnnotating(jobId);
    setError(null);
    try {
      await api.jobs.annotateSkip(jobId, reason, details[jobId]?.trim() || undefined);
      setDone((prev) => new Set(prev).add(jobId));
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to annotate");
    } finally {
      setAnnotating(null);
    }
  }

  async function annotateAll() {
    const pending = (skips || []).filter((s) => !done.has(s.job_id) && selectedReason[s.job_id]);
    if (pending.length === 0) return;
    setAnnotating(-1);
    setError(null);
    const errors: string[] = [];
    for (const s of pending) {
      try {
        await api.jobs.annotateSkip(s.job_id, selectedReason[s.job_id], details[s.job_id]?.trim() || undefined);
        setDone((prev) => new Set(prev).add(s.job_id));
      } catch (err) {
        errors.push(`Job ${s.job_id}: ${err instanceof Error ? err.message : "failed"}`);
      }
    }
    setAnnotating(null);
    if (errors.length > 0) {
      setError(`${errors.length}/${pending.length} failed — ${errors.slice(0, 3).join("; ")}${errors.length > 3 ? "…" : ""}`);
    }
  }

  const remaining = (skips || []).filter((s) => !done.has(s.job_id));
  const readyToAnnotate = remaining.filter((s) => selectedReason[s.job_id]).length;

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="outline" size="sm" disabled={demoMode}>
            <MinusCircle className="size-3.5" />
            Annotate Skips
          </Button>
        }
      />
      <DialogContent className="max-w-2xl max-h-[80vh] overflow-y-auto">
        <DialogHeader>
          <DialogTitle>Annotate Skip Reasons</DialogTitle>
          <DialogDescription>
            Add structured reasons to previously skipped/rejected jobs that have no reason.
            This data feeds the calibration report.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            {error}
          </div>
        )}

        {skips === null ? (
          <div className="flex items-center justify-center gap-2 py-8 text-sm text-muted-foreground">
            <Loader2 className="animate-spin" />
            Loading…
          </div>
        ) : skips.length === 0 ? (
          <div className="py-8 text-center text-sm text-muted-foreground">
            No skipped/rejected jobs missing a reason. All annotated!
          </div>
        ) : (
          <>
            <div className="flex items-center justify-between gap-2">
              <span className="text-sm text-muted-foreground">
                {remaining.length} job{remaining.length !== 1 ? "s" : ""} need a reason
                {readyToAnnotate > 0 && readyToAnnotate < remaining.length && ` (${readyToAnnotate} ready)`}
              </span>
              <Button
                size="sm"
                variant="default"
                disabled={readyToAnnotate === 0 || annotating !== null || demoMode}
                onClick={annotateAll}
              >
                {annotating === -1 ? <Loader2 className="size-3.5 animate-spin" /> : null}
                Annotate {readyToAnnotate > 0 ? readyToAnnotate : "All"}
              </Button>
            </div>
            <div className="flex flex-col gap-3">
              {remaining.map((s) => (
                <div key={s.job_id} className="rounded-lg border border-border p-3">
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0 flex-1">
                      <div className="truncate text-sm font-medium">
                        {s.title || "Untitled"}
                      </div>
                      <div className="text-xs text-muted-foreground">
                        {s.company || "Unknown"} · {s.status} · {s.event_type}
                      </div>
                    </div>
                    {done.has(s.job_id) && (
                      <span className="shrink-0 text-xs text-emerald-600 dark:text-emerald-400">
                        Done
                      </span>
                    )}
                  </div>
                  <div className="mt-2 flex flex-col gap-2">
                    <select
                      value={selectedReason[s.job_id] || ""}
                      onChange={(e) => {
                        setSelectedReason((prev) => ({ ...prev, [s.job_id]: e.target.value }));
                        setDetails((prev) => ({ ...prev, [s.job_id]: "" }));
                      }}
                      className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                    >
                      <option value="">Select a reason…</option>
                      {skipReasons.map((r) => (
                        <option key={r.key} value={r.key}>
                          {r.label || r.key}
                        </option>
                      ))}
                    </select>
                    {selectedReason[s.job_id] && (
                      <Textarea
                        value={details[s.job_id] || ""}
                        onChange={(e) => setDetails((prev) => ({ ...prev, [s.job_id]: e.target.value }))}
                        placeholder={reasonHint(selectedReason[s.job_id])}
                        rows={2}
                        className="text-sm"
                      />
                    )}
                    <Button
                      size="sm"
                      variant="outline"
                      disabled={!selectedReason[s.job_id] || annotating !== null || demoMode}
                      onClick={() => annotate(s.job_id)}
                    >
                      {annotating === s.job_id ? <Loader2 className="size-3.5 animate-spin" /> : null}
                      Save reason
                    </Button>
                  </div>
                </div>
              ))}
            </div>
          </>
        )}

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>
            Close
          </DialogClose>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
