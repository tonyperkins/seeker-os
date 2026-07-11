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
  Send,
  Users,
  Hand,
  ChevronDown,
  MoreHorizontal,
  ExternalLink,
  FileText,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogClose,
} from "@/components/ui/dialog";
import {
  DropdownMenu,
  DropdownMenuTrigger,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuLabel,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { DeleteButton } from "@/components/delete-button";
import { api, type SkipReasonOption } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

type TransitionDef = {
  status: string;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  needsDialog?: "reject" | "skip" | "override";
};

const STATUS_TRANSITIONS: Record<string, TransitionDef[]> = {
  ready: [
    { status: "reviewing", label: "Mark Reviewing", icon: Eye },
    { status: "interested", label: "Mark Interested", icon: Star },
    { status: "applied", label: "Mark Applied", icon: Send },
    { status: "skip", label: "Skip", icon: SkipForward, needsDialog: "skip" },
    { status: "reject", label: "Reject", icon: XCircle, needsDialog: "reject" },
  ],
  reviewing: [
    { status: "interested", label: "Mark Interested", icon: Star },
    { status: "ready", label: "Back to Ready", icon: CheckCircle2 },
    { status: "skip", label: "Skip", icon: SkipForward, needsDialog: "skip" },
    { status: "reject", label: "Reject", icon: XCircle, needsDialog: "reject" },
  ],
  interested: [
    { status: "reviewing", label: "Back to Reviewing", icon: Eye },
    { status: "applied", label: "Mark Applied", icon: Send },
    { status: "skip", label: "Skip", icon: SkipForward, needsDialog: "skip" },
    { status: "reject", label: "Reject", icon: XCircle, needsDialog: "reject" },
  ],
  skipped: [
    { status: "ready", label: "Reset to Ready", icon: CheckCircle2 },
  ],
  rejected: [
    { status: "override", label: "Override Rejection", icon: RotateCcw, needsDialog: "override" },
    { status: "ready", label: "Reset to Ready", icon: CheckCircle2 },
  ],
  applied: [
    { status: "engaged", label: "Mark Engaged", icon: Users },
    { status: "company_rejected", label: "Company Rejected", icon: XCircle },
    { status: "withdrawn", label: "Withdraw", icon: Hand },
    { status: "skip", label: "Skip", icon: SkipForward, needsDialog: "skip" },
  ],
  engaged: [
    { status: "offer_accepted", label: "Offer Accepted", icon: Send },
    { status: "offer_declined", label: "Offer Declined", icon: XCircle },
    { status: "company_rejected", label: "Company Rejected", icon: XCircle },
    { status: "withdrawn", label: "Withdraw", icon: Hand },
  ],
  company_rejected: [
    { status: "engaged", label: "Back to Engaged", icon: Users },
    { status: "withdrawn", label: "Withdraw", icon: Hand },
  ],
  withdrawn: [
    { status: "engaged", label: "Back to Engaged", icon: Users },
  ],
  offer_accepted: [
    { status: "engaged", label: "Back to Engaged", icon: Users },
  ],
  offer_declined: [
    { status: "engaged", label: "Back to Engaged", icon: Users },
  ],
};

const POST_APPLY_STATUSES = new Set([
  "applied", "engaged", "company_rejected", "withdrawn", "offer_accepted", "offer_declined",
]);

const STATUS_LABELS: Record<string, string> = {
  ready: "Ready",
  reviewing: "Reviewing",
  interested: "Interested",
  applied: "Applied",
  engaged: "Engaged",
  company_rejected: "Company Rejected",
  withdrawn: "Withdrawn",
  offer_accepted: "Offer Accepted",
  offer_declined: "Offer Declined",
  skipped: "Skipped",
  rejected: "Rejected",
};

interface JobActionsProps {
  jobId: number;
  currentStatus: string;
  hasResume?: boolean;
  applyUrl?: string;
  atsSource?: string | null;
}

export function JobActions({
  jobId,
  currentStatus,
  hasResume = false,
  applyUrl,
  atsSource,
}: JobActionsProps) {
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
    await api.jobs.delete(jobId);
    router.push("/jobs");
  }

  const transitions = STATUS_TRANSITIONS[currentStatus] ?? [];
  const isPostApply = POST_APPLY_STATUSES.has(currentStatus);

  // Derive the primary action from status + context
  let primaryAction: { label: string; icon: React.ComponentType<{ className?: string }>; onClick: () => void; busyKey?: string } | null = null;

  if (!isPostApply) {
    if (currentStatus === "ready" || currentStatus === "interested" || currentStatus === "reviewing") {
      if (applyUrl) {
        primaryAction = {
          label: `Apply on ${atsSource ?? "site"}`,
          icon: ExternalLink,
          onClick: () => window.open(applyUrl, "_blank", "noopener,noreferrer"),
        };
      } else {
        primaryAction = {
          label: "Mark Applied",
          icon: Send,
          onClick: () => doAction("apply", () => api.jobs.apply(jobId)),
          busyKey: "apply",
        };
      }
    } else if (currentStatus === "rejected") {
      primaryAction = {
        label: "Override Rejection",
        icon: RotateCcw,
        onClick: () => setOverrideOpen(true),
      };
    } else if (currentStatus === "skipped") {
      primaryAction = {
        label: "Reset to Ready",
        icon: CheckCircle2,
        onClick: () => doAction("ready", () => api.jobs.update(jobId, { status: "ready" })),
        busyKey: "ready",
      };
    }
  } else if (currentStatus === "applied") {
    primaryAction = {
      label: "Mark Engaged",
      icon: Users,
      onClick: () => doAction("transition-engaged", () => api.jobs.transition(jobId, "engaged")),
      busyKey: "transition-engaged",
    };
  }

  function handleTransition(t: TransitionDef) {
    if (t.needsDialog === "reject") {
      setRejectOpen(true);
    } else if (t.needsDialog === "skip") {
      setSkipOpen(true);
    } else if (t.needsDialog === "override") {
      setOverrideOpen(true);
    } else if (t.status === "ready") {
      doAction("ready", () => api.jobs.update(jobId, { status: "ready" }));
    } else {
      doAction(`transition-${t.status}`, () => api.jobs.transition(jobId, t.status));
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          {error}
        </div>
      )}
      {/* Primary action — one filled button derived from state */}
      {primaryAction && (
        <Button
          variant="default"
          size="lg"
          disabled={busy !== null || demoMode}
          onClick={primaryAction.onClick}
        >
          {primaryAction.busyKey && busy === primaryAction.busyKey ? (
            <Loader2 className="animate-spin" />
          ) : (
            <primaryAction.icon />
          )}
          {primaryAction.label}
        </Button>
      )}

      {/* Status dropdown — only valid transitions from current state */}
      {transitions.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="outline" disabled={busy !== null || demoMode}>
                Status: {STATUS_LABELS[currentStatus] ?? currentStatus}
                <ChevronDown />
              </Button>
            }
          />
          <DropdownMenuContent align="start">
            <DropdownMenuLabel>Change status</DropdownMenuLabel>
            <DropdownMenuSeparator />
            {transitions.map((t) => (
              <DropdownMenuItem
                key={t.status}
                onClick={() => handleTransition(t)}
                disabled={busy !== null || demoMode}
              >
                <t.icon />
                {t.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* Overflow menu — rare/destructive actions */}
      <DropdownMenu>
        <DropdownMenuTrigger
          render={
            <Button variant="ghost" size="sm" disabled={busy !== null || demoMode}>
              <MoreHorizontal />
              More
            </Button>
          }
        />
        <DropdownMenuContent align="start">
          {currentStatus !== "ready" && !transitions.some((t) => t.status === "ready") && (
            <DropdownMenuItem
              onClick={() => doAction("ready", () => api.jobs.update(jobId, { status: "ready" }))}
              disabled={busy !== null || demoMode}
            >
              <CheckCircle2 />
              Reset to Ready
            </DropdownMenuItem>
          )}
          {currentStatus === "rejected" && !transitions.some((t) => t.status === "override") && (
            <DropdownMenuItem
              onClick={() => setOverrideOpen(true)}
              disabled={busy !== null || demoMode}
            >
              <RotateCcw />
              Override Rejection
            </DropdownMenuItem>
          )}
          <DropdownMenuSeparator />
          <DeleteButton
            onDelete={handleDelete}
            itemName={`job #${jobId}`}
            itemId={jobId}
            size="sm"
            variant="ghost"
            label="Delete"
            triggerClassName="w-full justify-start text-destructive hover:text-destructive"
          />
        </DropdownMenuContent>
      </DropdownMenu>

      {/* Reject dialog */}
      <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
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

      {/* Skip dialog */}
      <Dialog open={skipOpen} onOpenChange={setSkipOpen}>
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

      {/* Override dialog */}
      <Dialog open={overrideOpen} onOpenChange={setOverrideOpen}>
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
    </div>
  );
}
