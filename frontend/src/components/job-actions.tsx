"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  XCircle,
  SkipForward,
  Eye,
  Star,
  Loader2,
  CheckCircle2,
  RotateCcw,
  Trash2,
} from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api } from "@/lib/api";

const REJECT_REASONS = [
  "comp_too_low",
  "wrong_seniority",
  "wrong_location",
  "tech_stack_mismatch",
  "not_remote",
  "duplicate",
  "not_relevant",
  "other",
];

const REASON_HINTS: Record<string, string> = {
  comp_too_low: "e.g. 'Max is $140K, below my floor of $150K'",
  wrong_seniority: "e.g. 'Entry-level role, I need senior+'",
  wrong_location: "e.g. 'Requires relocation to NYC'",
  tech_stack_mismatch: "e.g. 'Heavy on Java, I'm Python/Go'",
  not_remote: "e.g. '4 days onsite, I need full remote'",
  duplicate: "e.g. 'Same job as #42, different ATS posting'",
  not_relevant: "e.g. 'Solutions architect role, not infra/SRE'",
  other: "Describe what specifically doesn't fit...",
};

export function JobActions({ jobId, currentStatus }: { jobId: number; currentStatus: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectDetails, setRejectDetails] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideNote, setOverrideNote] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);

  async function doAction(
    key: string,
    fn: () => Promise<{ message: string }>,
    refresh = true,
  ) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      if (refresh) router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  async function handleDelete() {
    setBusy("delete");
    setError(null);
    try {
      await api.jobs.delete(jobId);
      router.push("/jobs");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete job");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          {error}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="outline"
          disabled={busy !== null || currentStatus === "reviewing"}
          onClick={() => doAction("reviewing", () => api.jobs.update(jobId, { status: "reviewing" }))}
        >
          {busy === "reviewing" ? <Loader2 className="animate-spin" /> : <Eye />}
          Mark Reviewing
        </Button>

        <Button
          variant="outline"
          disabled={busy !== null || currentStatus === "interested"}
          onClick={() => doAction("interested", () => api.jobs.update(jobId, { status: "interested" }))}
        >
          {busy === "interested" ? <Loader2 className="animate-spin" /> : <Star />}
          Mark Interested
        </Button>

        {/* Skip — removes from active queue */}
        <Button
          variant="outline"
          disabled={busy !== null}
          onClick={() => doAction("skip", () => api.jobs.skip(jobId))}
        >
          {busy === "skip" ? <Loader2 className="animate-spin" /> : <SkipForward />}
          Skip
        </Button>

        {/* Reject with reason dialog */}
        <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
          <DialogTrigger
            render={
              <Button variant="destructive" disabled={busy !== null}>
                {busy === "reject" ? <Loader2 className="animate-spin" /> : <XCircle />}
                Reject
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reject job</DialogTitle>
              <DialogDescription>
                Choose a reason and add details about what specifically doesn&rsquo;t fit.
                This feedback helps refine the filters for future job discovery.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="reject-reason">Reason</Label>
                <select
                  id="reject-reason"
                  value={rejectReason}
                  onChange={(e) => {
                    setRejectReason(e.target.value);
                    setRejectDetails("");
                  }}
                  className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                >
                  <option value="" className="bg-background text-foreground">Select a reason…</option>
                  {REJECT_REASONS.map((r) => (
                    <option key={r} value={r} className="bg-background text-foreground">
                      {r}
                    </option>
                  ))}
                </select>
              </div>
              {rejectReason && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="reject-details">
                    Details
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      (optional but helpful)
                    </span>
                  </Label>
                  <Textarea
                    id="reject-details"
                    value={rejectDetails}
                    onChange={(e) => setRejectDetails(e.target.value)}
                    placeholder={REASON_HINTS[rejectReason] || "What specifically about this job makes you reject it?"}
                    rows={3}
                    className="text-sm"
                  />
                </div>
              )}
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                variant="destructive"
                disabled={!rejectReason || busy !== null}
                onClick={() =>
                  doAction(
                    "reject",
                    () => api.jobs.reject(jobId, rejectReason, rejectDetails.trim() || undefined),
                    true,
                  ).then(() => {
                    setRejectOpen(false);
                    setRejectReason("");
                    setRejectDetails("");
                  })
                }
              >
                {busy === "reject" ? <Loader2 className="animate-spin" /> : <XCircle />}
                Confirm reject
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {currentStatus !== "ready" && (
          <Button
            variant="ghost"
            disabled={busy !== null}
            onClick={() => doAction("ready", () => api.jobs.update(jobId, { status: "ready" }))}
          >
            {busy === "ready" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
            Reset to Ready
          </Button>
        )}

        {/* Override rejection — auditable, only for rejected jobs */}
        {currentStatus === "rejected" && (
          <Dialog open={overrideOpen} onOpenChange={setOverrideOpen}>
            <DialogTrigger
              render={
                <Button variant="default" disabled={busy !== null}>
                  {busy === "override" ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                  Override Rejection
                </Button>
              }
            />
            <DialogContent>
              <DialogHeader>
                <DialogTitle>Override Rejection</DialogTitle>
                <DialogDescription>
                  This will move the job back to Ready and record the override with a timestamp.
                  The original rejection reason is preserved for audit.
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="override-note">
                    Note
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      (optional — why are you overriding?)
                    </span>
                  </Label>
                  <Textarea
                    id="override-note"
                    value={overrideNote}
                    onChange={(e) => setOverrideNote(e.target.value)}
                    placeholder="e.g. 'Want to apply anyway — good company culture'"
                    rows={3}
                    className="text-sm"
                  />
                </div>
              </div>
              <DialogFooter>
                <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                <Button
                  disabled={busy !== null}
                  onClick={() =>
                    doAction(
                      "override",
                      () => api.jobs.override(jobId, overrideNote.trim() || undefined),
                      true,
                    ).then(() => {
                      setOverrideOpen(false);
                      setOverrideNote("");
                    })
                  }
                >
                  {busy === "override" ? <Loader2 className="animate-spin" /> : <RotateCcw />}
                  Confirm Override
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        )}

        {/* Delete — permanent removal */}
        <Dialog open={deleteOpen} onOpenChange={setDeleteOpen}>
          <DialogTrigger
            render={
              <Button variant="ghost" disabled={busy !== null} className="text-destructive hover:text-destructive">
                {busy === "delete" ? <Loader2 className="animate-spin" /> : <Trash2 />}
                Delete
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Delete job</DialogTitle>
              <DialogDescription>
                This permanently deletes the job and all associated data (resumes,
                cover letters, analyses, research). This cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                variant="destructive"
                disabled={busy !== null}
                onClick={() => {
                  handleDelete();
                  setDeleteOpen(false);
                }}
              >
                {busy === "delete" ? <Loader2 className="animate-spin" /> : <Trash2 />}
                Delete permanently
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
