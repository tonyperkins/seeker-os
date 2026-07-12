"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  Loader2,
  Mail,
  Inbox,
  Users,
  Phone,
  StickyNote,
  NotebookPen,
} from "lucide-react";
import { api } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
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

export const ACTIVITY_TYPE_META: { type: string; label: string; icon: React.ComponentType<{ className?: string }> }[] = [
  { type: "note", label: "Note", icon: StickyNote },
  { type: "call", label: "Call", icon: Phone },
  { type: "email_sent", label: "Email Sent", icon: Mail },
  { type: "email_received", label: "Email Received", icon: Inbox },
  { type: "meeting", label: "Meeting", icon: Users },
  { type: "interview", label: "Interview", icon: Users },
];

function defaultDateTimeLocal(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
  return local.toISOString().slice(0, 16);
}

function toISOString(localDateTime: string): string {
  if (!localDateTime) return new Date().toISOString();
  return new Date(localDateTime).toISOString();
}

/** Single-CTA dialog for logging manual activity (note/call/email/meeting/
 *  interview). Type selection happens inside the dialog. With a jobId the
 *  event lands on that job's timeline; without one it's a general entry. */
export function LogActivityDialog({
  jobId,
  variant = "outline",
  onSuccess,
}: {
  jobId?: number | null;
  variant?: "default" | "outline" | "ghost";
  onSuccess?: () => void;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [eventType, setEventType] = useState("note");
  const [eventDate, setEventDate] = useState(defaultDateTimeLocal());
  const [eventNote, setEventNote] = useState("");

  function reset() {
    setEventType("note");
    setEventDate(defaultDateTimeLocal());
    setEventNote("");
    setError(null);
  }

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      await api.events.create({
        event_type: eventType,
        job_id: jobId ?? undefined,
        occurred_at: toISOString(eventDate),
        note: eventNote.trim() || undefined,
      });
      setOpen(false);
      reset();
      if (onSuccess) onSuccess();
      else router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to log activity");
    } finally {
      setBusy(false);
    }
  }

  const noteRequired = eventType === "note";

  return (
    <Dialog open={open} onOpenChange={(o) => { setOpen(o); if (o) reset(); }}>
      <DialogTrigger
        render={
          <Button variant={variant} size="sm">
            <NotebookPen className="size-4" />
            Log Activity
          </Button>
        }
      />
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Log Activity</DialogTitle>
          <DialogDescription>
            {jobId != null
              ? "Adds an entry to this job's timeline without changing its status. You can edit or delete it later."
              : "A general entry not tied to a job. To log against a specific job, use that job's page."}
          </DialogDescription>
        </DialogHeader>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1.5">
            <Label>Type</Label>
            <div className="flex flex-wrap gap-1.5">
              {ACTIVITY_TYPE_META.map((m) => (
                <Button
                  key={m.type}
                  type="button"
                  variant={eventType === m.type ? "default" : "outline"}
                  size="sm"
                  onClick={() => setEventType(m.type)}
                >
                  <m.icon className="size-3.5" />
                  {m.label}
                </Button>
              ))}
            </div>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="log-activity-date">Date / Time</Label>
            <Input
              id="log-activity-date"
              type="datetime-local"
              value={eventDate}
              onChange={(e) => setEventDate(e.target.value)}
            />
            <p className="text-xs text-muted-foreground">
              Defaults to now. Backdate if logging something that already happened.
            </p>
          </div>
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="log-activity-note">
              Note {noteRequired ? null : <span className="text-xs font-normal text-muted-foreground">(optional)</span>}
            </Label>
            <Textarea
              id="log-activity-note"
              value={eventNote}
              onChange={(e) => setEventNote(e.target.value)}
              rows={4}
              className="text-sm"
              autoFocus
            />
          </div>
          {error && (
            <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">{error}</div>
          )}
        </div>
        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button onClick={submit} disabled={busy || (noteRequired && !eventNote.trim())}>
            {busy ? <Loader2 className="animate-spin" /> : null}
            Log Activity
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
