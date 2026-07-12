"use client";

import { useState } from "react";
import {
  Loader2,
  Calendar,
  User,
  Building2,
  Cpu,
  Send,
  XCircle,
  Hand,
  Users,
  FileText,
  Upload,
  Mail,
  Inbox,
  Clock,
  Pencil,
  Trash2,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
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
import { api, type ApplicationEvent } from "@/lib/api";
import { formatDate } from "@/lib/date";
import { ACTIVITY_TYPE_META, LogActivityDialog } from "@/components/log-activity-dialog";

const ACTOR_ICONS: Record<string, React.ComponentType<{ className?: string }>> = {
  candidate: User,
  company: Building2,
  system: Cpu,
};

const EVENT_LABELS: Record<string, string> = {
  discovered: "Discovered",
  filter_passed: "Filter Passed",
  filter_rejected: "Filter Rejected",
  jd_fetched: "JD Fetched",
  jd_fetch_failed: "JD Fetch Failed",
  jd_fetch_retry: "JD Fetch Retry",
  duplicate_flagged: "Duplicate Flagged",
  scored_ready: "Scored Ready",
  scored_rejected: "Scored Rejected",
  capped: "Capped",
  manual_created: "Manual Created",
  status_changed: "Status Changed",
  rejected: "Rejected",
  skipped: "Skipped",
  overridden: "Overridden",
  resume_generated: "Resume Generated",
  applied: "Applied",
  company_rejected: "Company Rejected",
  withdrawn: "Withdrawn",
  engaged: "Engaged",
  offer_accepted: "Offer Accepted",
  offer_declined: "Offer Declined",
  interview: "Interview",
  challenge_assigned: "Challenge Assigned",
  challenge_submitted: "Challenge Submitted",
  offer_received: "Offer Received",
  offer_countered: "Offer Countered",
  followup_sent: "Follow-up Sent",
  contact_received: "Contact Received",
  refilter_rescored: "Refilter & Rescored",
  note: "Note",
  call: "Call",
  email_sent: "Email Sent",
  email_received: "Email Received",
  meeting: "Meeting",
};

// User-recorded activity — editable and deletable. Everything else in the
// timeline is append-only.
const MANUAL_TYPE_SET = new Set(ACTIVITY_TYPE_META.map((t) => t.type));

const POST_APPLY_TRANSITIONS: { status: string; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { status: "engaged", label: "Engaged", icon: Users },
  { status: "company_rejected", label: "Company Rejected", icon: XCircle },
  { status: "withdrawn", label: "Withdrawn", icon: Hand },
  { status: "offer_accepted", label: "Offer Accepted", icon: Send },
  { status: "offer_declined", label: "Offer Declined", icon: XCircle },
];

const ENGAGED_EVENT_TYPES: { type: string; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { type: "interview", label: "Interview", icon: Users },
  { type: "challenge_assigned", label: "Challenge Assigned", icon: FileText },
  { type: "challenge_submitted", label: "Challenge Submitted", icon: Upload },
  { type: "offer_received", label: "Offer Received", icon: Send },
  { type: "offer_countered", label: "Offer Countered", icon: Send },
  { type: "followup_sent", label: "Follow-up Sent", icon: Mail },
  { type: "contact_received", label: "Contact Received", icon: Inbox },
];

function defaultDateTimeLocal(): string {
  const now = new Date();
  const offset = now.getTimezoneOffset();
  const local = new Date(now.getTime() - offset * 60_000);
  return local.toISOString().slice(0, 16);
}

function isoToDateTimeLocal(iso: string): string {
  const dt = new Date(iso);
  if (isNaN(dt.getTime())) return defaultDateTimeLocal();
  const local = new Date(dt.getTime() - dt.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toISOString(localDateTime: string): string {
  if (!localDateTime) return new Date().toISOString();
  const dt = new Date(localDateTime);
  return dt.toISOString();
}

export function EventTimeline({
  jobId,
  initialEvents,
  currentStatus,
  isStale,
  daysSinceLastActivity,
}: {
  jobId: number;
  initialEvents: ApplicationEvent[];
  currentStatus: string;
  isStale: boolean;
  daysSinceLastActivity: number | null;
}) {
  const [events] = useState<ApplicationEvent[]>(initialEvents);
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [dialogOpen, setDialogOpen] = useState<string | null>(null);
  const [eventDate, setEventDate] = useState(defaultDateTimeLocal());
  const [eventNote, setEventNote] = useState("");
  const [appliedDate, setAppliedDate] = useState("");

  function resetDialogState() {
    setEventDate(defaultDateTimeLocal());
    setEventNote("");
    setAppliedDate("");
  }

  function refreshPage() {
    window.location.reload();
  }

  async function doTransition(targetStatus: string) {
    setBusy(`transition-${targetStatus}`);
    setError(null);
    try {
      await api.jobs.transition(jobId, targetStatus, {
        occurred_at: toISOString(eventDate),
        note: eventNote.trim() || undefined,
      });
      refreshPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Transition failed");
    } finally {
      setBusy(null);
      setDialogOpen(null);
      resetDialogState();
    }
  }

  async function doEngagedEvent(eventType: string) {
    setBusy(`engaged-${eventType}`);
    setError(null);
    try {
      await api.jobs.logEngagedEvent(jobId, eventType, {
        occurred_at: toISOString(eventDate),
        note: eventNote.trim() || undefined,
      });
      refreshPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log event");
    } finally {
      setBusy(null);
      setDialogOpen(null);
      resetDialogState();
    }
  }

  async function doEditEvent(eventId: number) {
    setBusy(`edit-${eventId}`);
    setError(null);
    try {
      await api.events.update(eventId, {
        occurred_at: toISOString(eventDate),
        note: eventNote.trim() || null,
      });
      refreshPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update event");
    } finally {
      setBusy(null);
      setDialogOpen(null);
      resetDialogState();
    }
  }

  async function doDeleteEvent(eventId: number) {
    setBusy(`delete-${eventId}`);
    setError(null);
    try {
      await api.events.delete(eventId);
      refreshPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete event");
    } finally {
      setBusy(null);
      setDialogOpen(null);
    }
  }

  async function doCleanStart(targetStatus: string) {
    setBusy(`clean-start-${targetStatus}`);
    setError(null);
    try {
      await api.jobs.cleanStart(jobId, targetStatus, {
        occurred_at: toISOString(eventDate),
        applied_occurred_at: appliedDate ? toISOString(appliedDate) : undefined,
        note: eventNote.trim() || undefined,
      });
      refreshPage();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Clean-start failed");
    } finally {
      setBusy(null);
      setDialogOpen(null);
      resetDialogState();
    }
  }

  const isPostApply = ["applied", "engaged", "company_rejected", "withdrawn", "offer_accepted", "offer_declined"].includes(currentStatus);
  const isEngaged = currentStatus === "engaged";
  const isPreApply = !isPostApply && currentStatus !== "rejected" && currentStatus !== "skipped" && currentStatus !== "capped";

  // Reserved for the follow-up event workflow; kept local until it is wired into the timeline.
  // eslint-disable-next-line @typescript-eslint/no-unused-vars
  function EventDialog({
    dialogKey,
    title,
    description,
    onConfirm,
    confirmLabel,
  }: {
    dialogKey: string;
    title: string;
    description: string;
    onConfirm: () => void;
    confirmLabel: string;
  }) {
    return (
      <Dialog open={dialogOpen === dialogKey} onOpenChange={(o) => { if (!o) setDialogOpen(null); }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>{title}</DialogTitle>
            <DialogDescription>{description}</DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="event-date">Date / Time</Label>
              <Input
                id="event-date"
                type="datetime-local"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Defaults to now. Backdate if logging something that already happened.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="event-note">
                Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Textarea
                id="event-note"
                value={eventNote}
                onChange={(e) => setEventNote(e.target.value)}
                rows={2}
                className="text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button onClick={onConfirm} disabled={busy !== null}>
              {busy !== null ? <Loader2 className="animate-spin" /> : null}
              {confirmLabel}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  function TransitionButton({
    status,
    label,
    icon: Icon,
  }: { status: string; label: string; icon: React.ComponentType<{ className?: string }> }) {
    return (
      <Dialog
        open={dialogOpen === `transition-${status}`}
        onOpenChange={(o) => { if (!o) setDialogOpen(null); else { setDialogOpen(`transition-${status}`); setEventDate(defaultDateTimeLocal()); setEventNote(""); } }}
      >
        <DialogTrigger
          render={
            <Button variant="outline" size="sm" disabled={busy !== null}>
              <Icon className="size-4" />
              {label}
            </Button>
          }
        />
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle>Transition to {label}</DialogTitle>
            <DialogDescription>
              This will change the job status to &ldquo;{status}&rdquo; and record a {label} event with the date below.
            </DialogDescription>
          </DialogHeader>
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="event-date">Date / Time</Label>
              <Input
                id="event-date"
                type="datetime-local"
                value={eventDate}
                onChange={(e) => setEventDate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Defaults to now. Backdate if logging something that already happened.
              </p>
            </div>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="event-note">
                Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
              </Label>
              <Textarea
                id="event-note"
                value={eventNote}
                onChange={(e) => setEventNote(e.target.value)}
                rows={2}
                className="text-sm"
              />
            </div>
          </div>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
            <Button onClick={() => doTransition(status)} disabled={busy !== null}>
              {busy === `transition-${status}` ? <Loader2 className="animate-spin" /> : null}
              Confirm
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <CollapsibleCard
      title="Event Timeline"
      description="Append-only audit trail of the application lifecycle"
      action={isStale ? (
        <Badge variant="outline" className="border-amber-500/50 text-amber-600 dark:text-amber-500">
          <Clock className="size-3" />
          Stale ({daysSinceLastActivity}d)
        </Badge>
      ) : undefined}
    >
      <div className="flex flex-col gap-4">
        {error && (
          <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            {error}
          </div>
        )}

        {/* Manual activity logging — available at any status */}
        <div className="flex flex-wrap gap-2">
          <LogActivityDialog jobId={jobId} />
        </div>

        {/* Post-apply transition controls */}
        {currentStatus === "applied" && (
          <div className="flex flex-wrap gap-2">
            {POST_APPLY_TRANSITIONS.filter(t => t.status !== "offer_accepted" && t.status !== "offer_declined").map(t => (
              <TransitionButton key={t.status} status={t.status} label={t.label} icon={t.icon} />
            ))}
          </div>
        )}
        {currentStatus === "engaged" && (
          <div className="flex flex-wrap gap-2">
            {POST_APPLY_TRANSITIONS.map(t => (
              <TransitionButton key={t.status} status={t.status} label={t.label} icon={t.icon} />
            ))}
          </div>
        )}

        {/* Engaged sub-event controls */}
        {isEngaged && (
          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            <span className="text-xs font-medium text-muted-foreground self-center">Log engaged event:</span>
            {ENGAGED_EVENT_TYPES.map(e => (
              <Dialog
                key={e.type}
                open={dialogOpen === `engaged-${e.type}`}
                onOpenChange={(o) => { if (!o) setDialogOpen(null); else { setDialogOpen(`engaged-${e.type}`); setEventDate(defaultDateTimeLocal()); setEventNote(""); } }}
              >
                <DialogTrigger
                  render={
                    <Button variant="ghost" size="sm" disabled={busy !== null}>
                      <e.icon className="size-3.5" />
                      {e.label}
                    </Button>
                  }
                />
                <DialogContent className="sm:max-w-md">
                  <DialogHeader>
                    <DialogTitle>Log: {e.label}</DialogTitle>
                    <DialogDescription>
                      This appends an event to the timeline without changing the job status.
                    </DialogDescription>
                  </DialogHeader>
                  <div className="flex flex-col gap-3">
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="event-date">Date / Time</Label>
                      <Input
                        id="event-date"
                        type="datetime-local"
                        value={eventDate}
                        onChange={(e2) => setEventDate(e2.target.value)}
                      />
                      <p className="text-xs text-muted-foreground">
                        Defaults to now. Backdate if logging something that already happened.
                      </p>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <Label htmlFor="event-note">
                        Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                      </Label>
                      <Textarea
                        id="event-note"
                        value={eventNote}
                        onChange={(e2) => setEventNote(e2.target.value)}
                        rows={2}
                        className="text-sm"
                      />
                    </div>
                  </div>
                  <DialogFooter>
                    <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                    <Button onClick={() => doEngagedEvent(e.type)} disabled={busy !== null}>
                      {busy === `engaged-${e.type}` ? <Loader2 className="animate-spin" /> : null}
                      Log Event
                    </Button>
                  </DialogFooter>
                </DialogContent>
              </Dialog>
            ))}
          </div>
        )}

        {/* Clean-start: enter directly at a post-apply status */}
        {isPreApply && (
          <div className="flex flex-wrap gap-2 border-t border-border pt-3">
            <span className="text-xs font-medium text-muted-foreground self-center">Clean-start (already applied?):</span>

            {/* Clean-start: Applied */}
            <Dialog
              open={dialogOpen === "clean-start-applied"}
              onOpenChange={(o) => { if (!o) setDialogOpen(null); else { setDialogOpen("clean-start-applied"); resetDialogState(); } }}
            >
              <DialogTrigger
                render={
                  <Button variant="ghost" size="sm" disabled={busy !== null}>
                    <Send className="size-3.5" />
                    Log Applied (backdated)
                  </Button>
                }
              />
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle>Clean-start: Applied</DialogTitle>
                  <DialogDescription>
                    Skip the pre-apply funnel and set this job directly to &ldquo;applied&rdquo; with a backdated event.
                    Use this when you&apos;ve already applied outside Seeker OS.
                  </DialogDescription>
                </DialogHeader>
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="event-date">Applied Date</Label>
                    <Input
                      id="event-date"
                      type="datetime-local"
                      value={eventDate}
                      onChange={(e) => setEventDate(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Set to the real date you applied.
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="event-note">
                      Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                    </Label>
                    <Textarea
                      id="event-note"
                      value={eventNote}
                      onChange={(e) => setEventNote(e.target.value)}
                      rows={2}
                      className="text-sm"
                    />
                  </div>
                </div>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                  <Button onClick={() => doCleanStart("applied")} disabled={busy !== null}>
                    {busy === "clean-start-applied" ? <Loader2 className="animate-spin" /> : null}
                    Set to Applied
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            {/* Clean-start: Engaged (with optional applied date) */}
            <Dialog
              open={dialogOpen === "clean-start-engaged"}
              onOpenChange={(o) => { if (!o) setDialogOpen(null); else { setDialogOpen("clean-start-engaged"); resetDialogState(); } }}
            >
              <DialogTrigger
                render={
                  <Button variant="ghost" size="sm" disabled={busy !== null}>
                    <Users className="size-3.5" />
                    Log Engaged (backdated)
                  </Button>
                }
              />
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle>Clean-start: Engaged</DialogTitle>
                  <DialogDescription>
                    Set this job directly to &ldquo;engaged&rdquo; with a backdated event.
                    If you know when you applied, supply that too for a complete history.
                  </DialogDescription>
                </DialogHeader>
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="event-date">Engaged Date</Label>
                    <Input
                      id="event-date"
                      type="datetime-local"
                      value={eventDate}
                      onChange={(e) => setEventDate(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Set to the real date you were engaged (interview, challenge, etc.).
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="applied-date">
                      Applied Date <span className="text-xs font-normal text-muted-foreground">(optional — leave blank if unknown)</span>
                    </Label>
                    <Input
                      id="applied-date"
                      type="datetime-local"
                      value={appliedDate}
                      onChange={(e) => setAppliedDate(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      If known, a backdated &ldquo;applied&rdquo; event will be created first.
                      Leave blank to enter at engaged with no applied event.
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="event-note">
                      Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                    </Label>
                    <Textarea
                      id="event-note"
                      value={eventNote}
                      onChange={(e) => setEventNote(e.target.value)}
                      rows={2}
                      className="text-sm"
                    />
                  </div>
                </div>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                  <Button onClick={() => doCleanStart("engaged")} disabled={busy !== null}>
                    {busy === "clean-start-engaged" ? <Loader2 className="animate-spin" /> : null}
                    Set to Engaged
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>

            {/* Clean-start: Company Rejected (with optional applied date) */}
            <Dialog
              open={dialogOpen === "clean-start-company_rejected"}
              onOpenChange={(o) => { if (!o) setDialogOpen(null); else { setDialogOpen("clean-start-company_rejected"); resetDialogState(); } }}
            >
              <DialogTrigger
                render={
                  <Button variant="ghost" size="sm" disabled={busy !== null}>
                    <XCircle className="size-3.5" />
                    Log Company Rejected (backdated)
                  </Button>
                }
              />
              <DialogContent className="sm:max-w-md">
                <DialogHeader>
                  <DialogTitle>Clean-start: Company Rejected</DialogTitle>
                  <DialogDescription>
                    Set this job directly to &ldquo;company_rejected&rdquo; with a backdated event.
                    If you know when you applied, supply that too for a complete history.
                  </DialogDescription>
                </DialogHeader>
                <div className="flex flex-col gap-3">
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="event-date">Rejection Date</Label>
                    <Input
                      id="event-date"
                      type="datetime-local"
                      value={eventDate}
                      onChange={(e) => setEventDate(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      Set to the real date you were rejected.
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="applied-date">
                      Applied Date <span className="text-xs font-normal text-muted-foreground">(optional — leave blank if unknown)</span>
                    </Label>
                    <Input
                      id="applied-date"
                      type="datetime-local"
                      value={appliedDate}
                      onChange={(e) => setAppliedDate(e.target.value)}
                    />
                    <p className="text-xs text-muted-foreground">
                      If known, a backdated &ldquo;applied&rdquo; event will be created first.
                      Leave blank to enter at rejected with no applied event.
                    </p>
                  </div>
                  <div className="flex flex-col gap-1.5">
                    <Label htmlFor="event-note">
                      Note <span className="text-xs font-normal text-muted-foreground">(optional)</span>
                    </Label>
                    <Textarea
                      id="event-note"
                      value={eventNote}
                      onChange={(e) => setEventNote(e.target.value)}
                      rows={2}
                      className="text-sm"
                    />
                  </div>
                </div>
                <DialogFooter>
                  <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                  <Button onClick={() => doCleanStart("company_rejected")} disabled={busy !== null}>
                    {busy === "clean-start-company_rejected" ? <Loader2 className="animate-spin" /> : null}
                    Set to Rejected
                  </Button>
                </DialogFooter>
              </DialogContent>
            </Dialog>
          </div>
        )}

        {/* Timeline */}
        <div className="flex flex-col gap-2">
          {events.length === 0 ? (
            <p className="text-sm text-muted-foreground">No events recorded.</p>
          ) : (
            events.map((event) => {
              const ActorIcon = ACTOR_ICONS[event.actor] ?? Cpu;
              const label = EVENT_LABELS[event.event_type] ?? event.event_type;
              const isManual = MANUAL_TYPE_SET.has(event.event_type);
              return (
                <div
                  key={event.id}
                  className="group flex items-start gap-3 rounded-lg border border-border/60 p-3"
                >
                  <div className="flex flex-col items-center gap-1 pt-0.5">
                    <ActorIcon className="size-4 text-muted-foreground" />
                  </div>
                  <div className="flex flex-col gap-1 flex-1 min-w-0">
                    <div className="flex items-center gap-2 flex-wrap">
                      <span className="text-sm font-medium">{label}</span>
                      <Badge variant="secondary" className="text-xs">{event.actor}</Badge>
                      {isManual && (
                        <span className="ml-auto flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                          <Dialog
                            open={dialogOpen === `edit-${event.id}`}
                            onOpenChange={(o) => {
                              if (!o) setDialogOpen(null);
                              else {
                                setDialogOpen(`edit-${event.id}`);
                                setEventDate(isoToDateTimeLocal(event.occurred_at));
                                setEventNote(event.note ?? "");
                              }
                            }}
                          >
                            <DialogTrigger
                              render={
                                <Button variant="ghost" size="icon-sm" aria-label={`Edit ${label}`} disabled={busy !== null}>
                                  <Pencil className="size-3.5" />
                                </Button>
                              }
                            />
                            <DialogContent className="sm:max-w-md">
                              <DialogHeader>
                                <DialogTitle>Edit: {label}</DialogTitle>
                                <DialogDescription>
                                  Update the date or note. System events cannot be edited — only manually logged activity.
                                </DialogDescription>
                              </DialogHeader>
                              <div className="flex flex-col gap-3">
                                <div className="flex flex-col gap-1.5">
                                  <Label htmlFor="event-date">Date / Time</Label>
                                  <Input
                                    id="event-date"
                                    type="datetime-local"
                                    value={eventDate}
                                    onChange={(e2) => setEventDate(e2.target.value)}
                                  />
                                </div>
                                <div className="flex flex-col gap-1.5">
                                  <Label htmlFor="event-note">Note</Label>
                                  <Textarea
                                    id="event-note"
                                    value={eventNote}
                                    onChange={(e2) => setEventNote(e2.target.value)}
                                    rows={3}
                                    className="text-sm"
                                  />
                                </div>
                              </div>
                              <DialogFooter>
                                <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                                <Button onClick={() => doEditEvent(event.id)} disabled={busy !== null}>
                                  {busy === `edit-${event.id}` ? <Loader2 className="animate-spin" /> : null}
                                  Save
                                </Button>
                              </DialogFooter>
                            </DialogContent>
                          </Dialog>
                          <Dialog
                            open={dialogOpen === `delete-${event.id}`}
                            onOpenChange={(o) => { if (!o) setDialogOpen(null); else setDialogOpen(`delete-${event.id}`); }}
                          >
                            <DialogTrigger
                              render={
                                <Button variant="ghost" size="icon-sm" aria-label={`Delete ${label}`} disabled={busy !== null}>
                                  <Trash2 className="size-3.5 text-destructive" />
                                </Button>
                              }
                            />
                            <DialogContent className="sm:max-w-md">
                              <DialogHeader>
                                <DialogTitle>Delete this {label.toLowerCase()}?</DialogTitle>
                                <DialogDescription>
                                  This permanently removes the entry from the timeline.
                                </DialogDescription>
                              </DialogHeader>
                              <DialogFooter>
                                <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                                <Button variant="destructive" onClick={() => doDeleteEvent(event.id)} disabled={busy !== null}>
                                  {busy === `delete-${event.id}` ? <Loader2 className="animate-spin" /> : null}
                                  Delete
                                </Button>
                              </DialogFooter>
                            </DialogContent>
                          </Dialog>
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                      <Calendar className="size-3" />
                      {formatDate(event.occurred_at)}
                    </div>
                    {event.note && (
                      <p className="text-xs text-muted-foreground mt-1">{event.note}</p>
                    )}
                    {event.metadata && Object.keys(event.metadata).length > 0 && (
                      <details className="mt-1">
                        <summary className="text-xs text-muted-foreground cursor-pointer">Metadata</summary>
                        <pre className="text-xs text-muted-foreground mt-1 overflow-x-auto">
                          {JSON.stringify(event.metadata, null, 2)}
                        </pre>
                      </details>
                    )}
                  </div>
                </div>
              );
            })
          )}
        </div>
      </div>
    </CollapsibleCard>
  );
}
