"use client";

import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import {
  Loader2,
  Calendar,
  Briefcase,
  Mail,
  Inbox,
  Users,
  Phone,
  StickyNote,
  Pencil,
  Trash2,
  Plus,
} from "lucide-react";
import { api, type ActivityEvent } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { Card, CardContent } from "@/components/ui/card";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { PageHeader } from "@/components/page-header";
import { formatDate } from "@/lib/date";

const PAGE_SIZE = 50;

const TYPE_META: Record<string, { label: string; icon: React.ComponentType<{ className?: string }> }> = {
  note: { label: "Note", icon: StickyNote },
  call: { label: "Call", icon: Phone },
  email_sent: { label: "Email Sent", icon: Mail },
  email_received: { label: "Email Received", icon: Inbox },
  meeting: { label: "Meeting", icon: Users },
  interview: { label: "Interview", icon: Users },
};

function defaultDateTimeLocal(): string {
  const now = new Date();
  const local = new Date(now.getTime() - now.getTimezoneOffset() * 60_000);
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
  return new Date(localDateTime).toISOString();
}

export default function ActivityPage() {
  const [events, setEvents] = useState<ActivityEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [hasMore, setHasMore] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [typeFilter, setTypeFilter] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  // Composer / edit dialog state
  const [dialogOpen, setDialogOpen] = useState<string | null>(null);
  const [composeType, setComposeType] = useState("note");
  const [eventDate, setEventDate] = useState(defaultDateTimeLocal());
  const [eventNote, setEventNote] = useState("");

  const load = useCallback(async (offset = 0, append = false) => {
    if (!append) setLoading(true);
    setError(null);
    try {
      const data = await api.events.list({
        manual_only: true,
        event_type: typeFilter ?? undefined,
        limit: PAGE_SIZE,
        offset,
      });
      setEvents((prev) => (append ? [...prev, ...data] : data));
      setHasMore(data.length === PAGE_SIZE);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load activity");
    } finally {
      setLoading(false);
    }
  }, [typeFilter]);

  useEffect(() => { load(); }, [load]);

  async function createEvent() {
    setBusy("create");
    setError(null);
    try {
      await api.events.create({
        event_type: composeType,
        occurred_at: toISOString(eventDate),
        note: eventNote.trim() || undefined,
      });
      setDialogOpen(null);
      setEventNote("");
      setEventDate(defaultDateTimeLocal());
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save");
    } finally {
      setBusy(null);
    }
  }

  async function saveEdit(id: number) {
    setBusy(`edit-${id}`);
    setError(null);
    try {
      await api.events.update(id, {
        occurred_at: toISOString(eventDate),
        note: eventNote.trim() || null,
      });
      setDialogOpen(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to update");
    } finally {
      setBusy(null);
    }
  }

  async function deleteEvent(id: number) {
    setBusy(`delete-${id}`);
    setError(null);
    try {
      await api.events.delete(id);
      setDialogOpen(null);
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <PageHeader
        title="Activity"
        description="Notes, calls, emails, and meetings — job-linked and general"
        actions={
          <Dialog
            open={dialogOpen === "compose"}
            onOpenChange={(o) => {
              if (!o) setDialogOpen(null);
              else { setDialogOpen("compose"); setEventDate(defaultDateTimeLocal()); setEventNote(""); }
            }}
          >
            <Button onClick={() => { setDialogOpen("compose"); setEventDate(defaultDateTimeLocal()); setEventNote(""); }}>
              <Plus className="size-4" />
              Log Activity
            </Button>
            <DialogContent className="sm:max-w-md">
              <DialogHeader>
                <DialogTitle>Log Activity</DialogTitle>
                <DialogDescription>
                  A general entry not tied to a job. To log activity against a
                  specific job, use the timeline on that job&apos;s page.
                </DialogDescription>
              </DialogHeader>
              <div className="flex flex-col gap-3">
                <div className="flex flex-col gap-1.5">
                  <Label>Type</Label>
                  <div className="flex flex-wrap gap-1.5">
                    {Object.entries(TYPE_META).map(([type, meta]) => (
                      <Button
                        key={type}
                        type="button"
                        variant={composeType === type ? "default" : "outline"}
                        size="sm"
                        onClick={() => setComposeType(type)}
                      >
                        <meta.icon className="size-3.5" />
                        {meta.label}
                      </Button>
                    ))}
                  </div>
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="activity-date">Date / Time</Label>
                  <Input
                    id="activity-date"
                    type="datetime-local"
                    value={eventDate}
                    onChange={(e) => setEventDate(e.target.value)}
                  />
                </div>
                <div className="flex flex-col gap-1.5">
                  <Label htmlFor="activity-note">Note</Label>
                  <Textarea
                    id="activity-note"
                    value={eventNote}
                    onChange={(e) => setEventNote(e.target.value)}
                    rows={4}
                    className="text-sm"
                    autoFocus
                  />
                </div>
              </div>
              <DialogFooter>
                <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                <Button onClick={createEvent} disabled={busy !== null || !eventNote.trim()}>
                  {busy === "create" ? <Loader2 className="animate-spin" /> : null}
                  Save
                </Button>
              </DialogFooter>
            </DialogContent>
          </Dialog>
        }
      />

      {/* Type filter */}
      <div className="flex flex-wrap gap-1.5">
        <Button
          variant={typeFilter === null ? "secondary" : "ghost"}
          size="sm"
          onClick={() => setTypeFilter(null)}
        >
          All
        </Button>
        {Object.entries(TYPE_META).map(([type, meta]) => (
          <Button
            key={type}
            variant={typeFilter === type ? "secondary" : "ghost"}
            size="sm"
            onClick={() => setTypeFilter(type)}
          >
            <meta.icon className="size-3.5" />
            {meta.label}
          </Button>
        ))}
      </div>

      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">{error}</div>
      )}

      {loading ? (
        <div className="flex justify-center py-12">
          <Loader2 className="size-6 animate-spin text-muted-foreground" />
        </div>
      ) : events.length === 0 ? (
        <Card>
          <CardContent className="py-10 text-center text-sm text-muted-foreground">
            No activity logged yet. Use &ldquo;Log Activity&rdquo; for general notes, or log
            against a job from its timeline.
          </CardContent>
        </Card>
      ) : (
        <div className="flex flex-col gap-2">
          {events.map((event) => {
            const meta = TYPE_META[event.event_type] ?? { label: event.event_type, icon: StickyNote };
            const Icon = meta.icon;
            return (
              <div
                key={event.id}
                className="group flex items-start gap-3 rounded-lg border border-border/60 p-3"
              >
                <Icon className="size-4 text-muted-foreground mt-0.5" />
                <div className="flex flex-col gap-1 flex-1 min-w-0">
                  <div className="flex items-center gap-2 flex-wrap">
                    <span className="text-sm font-medium">{meta.label}</span>
                    {event.job_id !== null ? (
                      <Link href={`/jobs/${event.job_id}`}>
                        <Badge variant="outline" className="text-xs hover:bg-accent">
                          <Briefcase className="size-3" />
                          {event.job_title ?? `Job #${event.job_id}`}
                          {event.job_company ? ` — ${event.job_company}` : ""}
                        </Badge>
                      </Link>
                    ) : (
                      <Badge variant="secondary" className="text-xs">General</Badge>
                    )}
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
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="Edit"
                          disabled={busy !== null}
                          onClick={() => {
                            setDialogOpen(`edit-${event.id}`);
                            setEventDate(isoToDateTimeLocal(event.occurred_at));
                            setEventNote(event.note ?? "");
                          }}
                        >
                          <Pencil className="size-3.5" />
                        </Button>
                        <DialogContent className="sm:max-w-md">
                          <DialogHeader>
                            <DialogTitle>Edit: {meta.label}</DialogTitle>
                            <DialogDescription>Update the date or note.</DialogDescription>
                          </DialogHeader>
                          <div className="flex flex-col gap-3">
                            <div className="flex flex-col gap-1.5">
                              <Label htmlFor="edit-date">Date / Time</Label>
                              <Input
                                id="edit-date"
                                type="datetime-local"
                                value={eventDate}
                                onChange={(e) => setEventDate(e.target.value)}
                              />
                            </div>
                            <div className="flex flex-col gap-1.5">
                              <Label htmlFor="edit-note">Note</Label>
                              <Textarea
                                id="edit-note"
                                value={eventNote}
                                onChange={(e) => setEventNote(e.target.value)}
                                rows={4}
                                className="text-sm"
                              />
                            </div>
                          </div>
                          <DialogFooter>
                            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                            <Button onClick={() => saveEdit(event.id)} disabled={busy !== null}>
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
                        <Button
                          variant="ghost"
                          size="icon-sm"
                          aria-label="Delete"
                          disabled={busy !== null}
                          onClick={() => setDialogOpen(`delete-${event.id}`)}
                        >
                          <Trash2 className="size-3.5 text-destructive" />
                        </Button>
                        <DialogContent className="sm:max-w-md">
                          <DialogHeader>
                            <DialogTitle>Delete this {meta.label.toLowerCase()}?</DialogTitle>
                            <DialogDescription>This permanently removes the entry.</DialogDescription>
                          </DialogHeader>
                          <DialogFooter>
                            <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
                            <Button variant="destructive" onClick={() => deleteEvent(event.id)} disabled={busy !== null}>
                              {busy === `delete-${event.id}` ? <Loader2 className="animate-spin" /> : null}
                              Delete
                            </Button>
                          </DialogFooter>
                        </DialogContent>
                      </Dialog>
                    </span>
                  </div>
                  <div className="flex items-center gap-1.5 text-xs text-muted-foreground">
                    <Calendar className="size-3" />
                    {formatDate(event.occurred_at)}
                  </div>
                  {event.note && (
                    <p className="text-sm whitespace-pre-wrap mt-1">{event.note}</p>
                  )}
                </div>
              </div>
            );
          })}
          {hasMore && (
            <Button
              variant="outline"
              className="self-center"
              onClick={() => load(events.length, true)}
            >
              Load more
            </Button>
          )}
        </div>
      )}
    </div>
  );
}
