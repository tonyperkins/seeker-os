"use client";

import { useState, useEffect } from "react";
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
  Send,
  Users,
  Hand,
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
import { api, type SkipReasonOption } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

type TransitionDef = { status: string; label: string; icon: React.ComponentType<{ className?: string }>; variant?: "default" | "outline" | "destructive" };

const POST_APPLY_TRANSITIONS: Record<string, TransitionDef[]> = {
  applied: [
    { status: "engaged", label: "Mark Engaged", icon: Users, variant: "default" },
    { status: "company_rejected", label: "Company Rejected", icon: XCircle, variant: "outline" },
    { status: "withdrawn", label: "Withdraw", icon: Hand, variant: "outline" },
  ],
  engaged: [
    { status: "offer_accepted", label: "Offer Accepted", icon: Send, variant: "default" },
    { status: "offer_declined", label: "Offer Declined", icon: XCircle, variant: "outline" },
    { status: "company_rejected", label: "Company Rejected", icon: XCircle, variant: "outline" },
    { status: "withdrawn", label: "Withdraw", icon: Hand, variant: "outline" },
  ],
};

const POST_APPLY_STATUSES = new Set(["applied", "engaged", "company_rejected", "withdrawn", "offer_accepted", "offer_declined"]);

export function JobActions({ jobId, currentStatus }: { jobId: number; currentStatus: string }) {
  const { demoMode } = useDemoMode();
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [rejectDetails, setRejectDetails] = useState("");
  const [rejectOpen, setRejectOpen] = useState(false);
  const [skipOpen, setSkipOpen] = useState(false);
  const [skipReason, setSkipReason] = useState("");
  const [skipDetails, setSkipDetails] = useState("");
  const [skipReasons, setSkipReasons] = useState<SkipReasonOption[]>([]);
  const [overrideOpen, setOverrideOpen] = useState(false);
  const [overrideNote, setOverrideNote] = useState("");
  const [deleteOpen, setDeleteOpen] = useState(false);

  useEffect(() => {
    api.settings.get().then((s) => {
      if (s.skip_reasons?.length) setSkipReasons(s.skip_reasons);
    }).catch(() => {});
  }, []);

  const reasonHint = (key: string): string => {
    const r = skipReasons.find((sr) => sr.key === key);
    return r?.hint || "What specifically about this job doesn't fit?";
  };

  async function doAction(
    key: string,
    fn: () => Promise<{ message: string }>,
    refresh = true,
  ) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      window.dispatchEvent(new Event("job-status-changed"));
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
      {/* Post-apply transition CTAs */}
      {POST_APPLY_TRANSITIONS[currentStatus] && (
        <div className="flex flex-wrap gap-2 border-b border-border pb-3">
          {POST_APPLY_TRANSITIONS[currentStatus].map((t) => (
            <Button
              key={t.status}
              variant={t.variant || "outline"}
              disabled={busy !== null || demoMode}
              onClick={() => doAction(`transition-${t.status}`, () => api.jobs.transition(jobId, t.status))}
            >
              {busy === `transition-${t.status}` ? <Loader2 className="animate-spin" /> : <t.icon />}
              {t.label}
            </Button>
          ))}
        </div>
      )}

      <div className="flex flex-wrap gap-2">
        {/* Pre-apply actions — hidden when in post-apply states */}
        {!POST_APPLY_STATUSES.has(currentStatus) && (
          <>
            <Button
              variant="outline"
              disabled={busy !== null || currentStatus === "reviewing" || demoMode}
              onClick={() => doAction("reviewing", () => api.jobs.update(jobId, { status: "reviewing" }))}
            >
              {busy === "reviewing" ? <Loader2 className="animate-spin" /> : <Eye />}
              Mark Reviewing
            </Button>

            <Button
              variant="outline"
              disabled={busy !== null || currentStatus === "interested" || demoMode}
              onClick={() => doAction("interested", () => api.jobs.update(jobId, { status: "interested" }))}
            >
              {busy === "interested" ? <Loader2 className="animate-spin" /> : <Star />}
              Mark Interested
            </Button>

            {/* Mark Applied — records APPLIED event */}
            <Button
              variant="default"
              disabled={busy !== null || currentStatus === "applied" || demoMode}
              onClick={() => doAction("apply", () => api.jobs.apply(jobId))}
            >
              {busy === "apply" ? <Loader2 className="animate-spin" /> : <Send />}
              Mark Applied
            </Button>

            {/* Skip — opens optional reason dialog (dismissible — skip proceeds without reason) */}
            <Dialog open={skipOpen} onOpenChange={setSkipOpen}>
          <DialogTrigger
            render={
              <Button variant="outline" disabled={busy !== null || demoMode}>
                {busy === "skip" ? <Loader2 className="animate-spin" /> : <SkipForward />}
                Skip
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Skip job</DialogTitle>
              <DialogDescription>
                Optional: choose a reason to help calibrate scoring. You can skip
                without a reason — just click Skip below.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="skip-reason">
                  Reason
                  <span className="ml-1 text-xs font-normal text-muted-foreground">
                    (optional)
                  </span>
                </Label>
                <select
                  id="skip-reason"
                  value={skipReason}
                  onChange={(e) => {
                    setSkipReason(e.target.value);
                    setSkipDetails("");
                  }}
                  className="h-8 rounded-lg border border-input bg-background px-2.5 text-sm text-foreground outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                >
                  <option value="" className="bg-background text-foreground">No reason (just skip)</option>
                  {skipReasons.map((r) => (
                    <option key={r.key} value={r.key} className="bg-background text-foreground">
                      {r.label || r.key}
                    </option>
                  ))}
                </select>
              </div>
              {skipReason && (
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="skip-details">
                    Details
                    <span className="ml-1 text-xs font-normal text-muted-foreground">
                      (optional but helpful)
                    </span>
                  </Label>
                  <Textarea
                    id="skip-details"
                    value={skipDetails}
                    onChange={(e) => setSkipDetails(e.target.value)}
                    placeholder={reasonHint(skipReason)}
                    rows={3}
                    className="text-sm"
                  />
                </div>
              )}
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                variant="outline"
                disabled={busy !== null || demoMode}
                onClick={() =>
                  doAction(
                    "skip",
                    () => api.jobs.skip(jobId, skipReason || undefined, skipDetails.trim() || undefined),
                    true,
                  ).then(() => {
                    setSkipOpen(false);
                    setSkipReason("");
                    setSkipDetails("");
                  })
                }
              >
                {busy === "skip" ? <Loader2 className="animate-spin" /> : <SkipForward />}
                Skip{skipReason ? " with reason" : ""}
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

            {/* Reject with reason dialog */}
            <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
          <DialogTrigger
            render={
              <Button variant="destructive" disabled={busy !== null || demoMode}>
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
                  {skipReasons.map((r) => (
                    <option key={r.key} value={r.key} className="bg-background text-foreground">
                      {r.label || r.key}
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
                    placeholder={reasonHint(rejectReason)}
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
                disabled={!rejectReason || busy !== null || demoMode}
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
          </>
        )}

        {currentStatus !== "ready" && (
          <Button
            variant="ghost"
            disabled={busy !== null || demoMode}
            onClick={() => doAction("ready", () => api.jobs.update(jobId, { status: "ready" }))}
          >
            {busy === "ready" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
            Reset to Ready
          </Button>
        )}

        {/* Skip — available in post-apply states too (opens reason dialog) */}
        {POST_APPLY_STATUSES.has(currentStatus) && (
          <Button
            variant="outline"
            disabled={busy !== null || demoMode}
            onClick={() => setSkipOpen(true)}
          >
            {busy === "skip" ? <Loader2 className="animate-spin" /> : <SkipForward />}
            Skip
          </Button>
        )}

        {/* Override rejection — auditable, only for rejected jobs */}
        {currentStatus === "rejected" && (
          <Dialog open={overrideOpen} onOpenChange={setOverrideOpen}>
            <DialogTrigger
              render={
                <Button variant="default" disabled={busy !== null || demoMode}>
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
                  disabled={busy !== null || demoMode}
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
              <Button variant="ghost" disabled={busy !== null || demoMode} className="text-destructive hover:text-destructive">
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
                analyses, research). This cannot be undone.
              </DialogDescription>
            </DialogHeader>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                variant="destructive"
                disabled={busy !== null || demoMode}
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
