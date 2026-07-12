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
  ExternalLink,
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
  DropdownMenuGroup,
} from "@/components/ui/dropdown-menu";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { GenerateResumeButton } from "@/components/generate-resume-button";
import { api, type SkipReasonOption } from "@/lib/api";

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
  analysisVerdict?: string | null;
}

export type PrimaryActionType =
  | "generate-resume"
  | "apply-on-site"
  | "mark-applied"
  | "mark-engaged"
  | "override-rejection"
  | "reset-to-ready";

export interface PrimaryAction {
  type: PrimaryActionType;
  label: string;
  icon: React.ComponentType<{ className?: string }>;
  statusTarget: string;
}

export function getPrimaryAction(job: {
  status: string;
  has_resume: boolean;
  apply_url: string;
  ats_source: string | null;
  analysis_verdict: string | null;
}): PrimaryAction | null {
  switch (job.status) {
    case "ready":
      if (job.has_resume) {
        if (job.apply_url) {
          return {
            type: "apply-on-site",
            label: `Apply on ${job.ats_source ?? "site"}`,
            icon: ExternalLink,
            statusTarget: "",
          };
        }
        return {
          type: "mark-applied",
          label: "Mark Applied",
          icon: Send,
          statusTarget: "applied",
        };
      }
      if (job.analysis_verdict === "APPLY" || job.analysis_verdict === "CONDITIONAL") {
        return {
          type: "generate-resume",
          label: "Generate Resume",
          icon: Send,
          statusTarget: "",
        };
      }
      return null;
    case "applied":
      return {
        type: "mark-engaged",
        label: "Mark Engaged",
        icon: Users,
        statusTarget: "engaged",
      };
    case "rejected":
      return {
        type: "override-rejection",
        label: "Override Rejection",
        icon: RotateCcw,
        statusTarget: "override",
      };
    case "skipped":
      return {
        type: "reset-to-ready",
        label: "Reset to Ready",
        icon: CheckCircle2,
        statusTarget: "ready",
      };
    default:
      return null;
  }
}

export function JobActions({
  jobId,
  currentStatus,
  hasResume = false,
  applyUrl,
  atsSource,
  analysisVerdict,
}: JobActionsProps) {
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

  const primary = getPrimaryAction({
    status: currentStatus,
    has_resume: hasResume,
    apply_url: applyUrl ?? "",
    ats_source: atsSource ?? null,
    analysis_verdict: analysisVerdict ?? null,
  });

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

  const allTransitions = STATUS_TRANSITIONS[currentStatus] ?? [];
  const transitions = primary
    ? allTransitions.filter((t) => t.status !== primary.statusTarget)
    : allTransitions;

  function handleTransition(t: TransitionDef) {
    if (t.needsDialog === "reject") {
      setRejectOpen(true);
    } else if (t.needsDialog === "skip") {
      setSkipOpen(true);
    } else if (t.needsDialog === "override") {
      setOverrideOpen(true);
    } else if (t.status === "ready") {
      doAction("ready", () => api.jobs.update(jobId, { status: "ready" }));
    } else if (t.status === "applied") {
      doAction("apply", () => api.jobs.apply(jobId));
    } else if (t.status === "reviewing" || t.status === "interested") {
      doAction(`transition-${t.status}`, () => api.jobs.update(jobId, { status: t.status }));
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
      {/* Zone 1: Primary action — one filled button derived from state */}
      {primary?.type === "generate-resume" ? (
        <GenerateResumeButton jobId={jobId} size="lg" />
      ) : primary ? (
        <Button
          variant="default"
          size="lg"
          disabled={busy !== null}
          onClick={() => {
            if (primary.type === "apply-on-site" && applyUrl) {
              window.open(applyUrl, "_blank", "noopener,noreferrer");
            } else if (primary.type === "mark-applied") {
              doAction("apply", () => api.jobs.apply(jobId));
            } else if (primary.type === "mark-engaged") {
              doAction("transition-engaged", () => api.jobs.transition(jobId, "engaged"));
            } else if (primary.type === "override-rejection") {
              setOverrideOpen(true);
            } else if (primary.type === "reset-to-ready") {
              doAction("ready", () => api.jobs.update(jobId, { status: "ready" }));
            }
          }}
        >
          {((primary.type === "mark-applied" && busy === "apply") ||
            (primary.type === "mark-engaged" && busy === "transition-engaged") ||
            (primary.type === "reset-to-ready" && busy === "ready")) && (
            <Loader2 className="animate-spin" />
          )}
          {primary.type === "apply-on-site" && <ExternalLink />}
          {primary.type === "mark-applied" && busy !== "apply" && <Send />}
          {primary.type === "mark-engaged" && busy !== "transition-engaged" && <Users />}
          {primary.type === "override-rejection" && <RotateCcw />}
          {primary.type === "reset-to-ready" && busy !== "ready" && <CheckCircle2 />}
          {primary.label}
        </Button>
      ) : null}

      {/* Zone 2: Status dropdown — all valid transitions minus the primary */}
      {transitions.length > 0 && (
        <DropdownMenu>
          <DropdownMenuTrigger
            render={
              <Button variant="outline" disabled={busy !== null}>
                Status: {STATUS_LABELS[currentStatus] ?? currentStatus}
                <ChevronDown />
              </Button>
            }
          />
          <DropdownMenuContent align="start">
            <DropdownMenuGroup>
              <DropdownMenuLabel>Change status</DropdownMenuLabel>
            </DropdownMenuGroup>
            <DropdownMenuSeparator />
            {transitions.map((t) => (
              <DropdownMenuItem
                key={t.status}
                onClick={() => handleTransition(t)}
                disabled={busy !== null}
              >
                <t.icon />
                {t.label}
              </DropdownMenuItem>
            ))}
          </DropdownMenuContent>
        </DropdownMenu>
      )}

      {/* Apply on site — secondary when not already the primary */}
      {applyUrl && primary?.type !== "apply-on-site" && (
        <Button
          variant="outline"
          size="lg"
          disabled={busy !== null}
          onClick={() => window.open(applyUrl, "_blank", "noopener,noreferrer")}
        >
          <ExternalLink />
          Apply on {atsSource ?? "site"}
        </Button>
      )}

      {/* Generate Resume as secondary when it's not the primary */}
      {(!primary || primary.type !== "generate-resume") && (
        <GenerateResumeButton jobId={jobId} variant="outline" />
      )}

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
              disabled={busy !== null}
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
    </div>
  );
}
