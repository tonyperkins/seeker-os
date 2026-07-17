"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  DndContext,
  closestCenter,
  KeyboardSensor,
  PointerSensor,
  useSensor,
  useSensors,
  type DragEndEvent,
} from "@dnd-kit/core";
import {
  SortableContext,
  arrayMove,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import { ArrowRight, GripVertical } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { STATUS_LABELS, StaleBadge } from "@/components/dashboard-post-ready";
import { api, type JobSummary } from "@/lib/api";

const ACTIVE_STATUSES = new Set(["applied", "engaged", "offer_accepted", "offer_declined"]);

/** Ranked-first sort: ranked jobs (ascending rank) before unranked jobs
 * (tie-broken by days since last activity, most stale first — matches the
 * default "recent activity" ordering). */
function byPreference(a: JobSummary, b: JobSummary): number {
  const aRank = a.preference_rank ?? Number.MAX_SAFE_INTEGER;
  const bRank = b.preference_rank ?? Number.MAX_SAFE_INTEGER;
  if (aRank !== bRank) return aRank - bRank;
  return (b.days_since_last_activity ?? 0) - (a.days_since_last_activity ?? 0);
}

function byRecentActivity(a: JobSummary, b: JobSummary): number {
  return (b.days_since_last_activity ?? 0) - (a.days_since_last_activity ?? 0);
}

function SortableJobRow({ job }: { job: JobSummary; rank: number }) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } = useSortable({
    id: job.id,
  });
  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
  };
  const days = job.days_since_last_activity ?? 0;

  return (
    <div
      ref={setNodeRef}
      style={style}
      className={`flex items-center gap-3 py-2.5 text-sm -mx-2 px-2 rounded-md ${
        isDragging ? "bg-muted/60 shadow-sm z-10" : ""
      }`}
    >
      <button
        type="button"
        aria-label="Drag to reorder"
        className="shrink-0 cursor-grab touch-none text-muted-foreground hover:text-foreground active:cursor-grabbing"
        {...attributes}
        {...listeners}
      >
        <GripVertical className="size-4" />
      </button>
      <Link
        href={`/jobs/${job.id}`}
        className="min-w-0 flex-1 transition-opacity hover:opacity-70"
      >
        <span className="block truncate font-medium">{job.title}</span>
        <span className="block truncate text-muted-foreground">{job.company}</span>
      </Link>
      <div className="flex w-16 shrink-0 justify-end">
        <StaleBadge days={days} />
      </div>
      <Badge variant="secondary" className="text-xs">
        {STATUS_LABELS[job.status] ?? job.status}
      </Badge>
      <Link href={`/jobs/${job.id}`} className="shrink-0 text-muted-foreground hover:text-foreground">
        <ArrowRight className="size-4" />
      </Link>
    </div>
  );
}

export function RankedApplications({ jobs }: { jobs: JobSummary[] }) {
  const router = useRouter();
  const [mode, setMode] = useState<"recent" | "ranked">("recent");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const active = jobs.filter((j) => ACTIVE_STATUSES.has(j.status));
  const rejectedCount = jobs.filter(
    (j) => j.status === "company_rejected" || j.status === "withdrawn",
  ).length;

  // Re-derive ranked order whenever the underlying jobs prop changes (e.g. after
  // router.refresh() following a save) — adjusting state during render instead of
  // an effect avoids an extra render pass. See https://react.dev/learn/you-might-not-need-an-effect#adjusting-some-state-when-a-prop-changes
  const [prevJobs, setPrevJobs] = useState(jobs);
  const [order, setOrder] = useState<JobSummary[]>(() => [...active].sort(byPreference));
  if (jobs !== prevJobs) {
    setPrevJobs(jobs);
    setOrder([...active].sort(byPreference));
  }

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  async function handleDragEnd(event: DragEndEvent) {
    const { active: draggedItem, over } = event;
    if (!over || draggedItem.id === over.id) return;

    const oldIndex = order.findIndex((j) => j.id === draggedItem.id);
    const newIndex = order.findIndex((j) => j.id === over.id);
    if (oldIndex === -1 || newIndex === -1) return;

    const reordered = arrayMove(order, oldIndex, newIndex);
    setOrder(reordered);
    setSaving(true);
    setError(null);
    try {
      await api.jobs.reorder(reordered.map((j) => j.id));
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to save ranking");
    } finally {
      setSaving(false);
    }
  }

  const displayed = mode === "ranked" ? order : [...active].sort(byRecentActivity);

  return (
    <div className="flex flex-col min-h-0">
      <div className="mb-2 flex items-center justify-between gap-2 shrink-0">
        {rejectedCount > 0 ? (
          <div className="rounded-md bg-muted/40 px-3 py-1.5 text-xs text-muted-foreground">
            <span className="font-mono font-medium text-foreground">{rejectedCount}</span> rejected · auto-archived
          </div>
        ) : (
          <div />
        )}
        <div className="flex shrink-0 gap-1">
          <Button
            type="button"
            size="xs"
            variant={mode === "recent" ? "outline" : "ghost"}
            onClick={() => setMode("recent")}
          >
            Recent activity
          </Button>
          <Button
            type="button"
            size="xs"
            variant={mode === "ranked" ? "outline" : "ghost"}
            onClick={() => setMode("ranked")}
          >
            My ranking
          </Button>
        </div>
      </div>

      {error && (
        <div className="mb-2 rounded-md bg-destructive/10 px-2.5 py-1.5 text-xs text-destructive shrink-0">
          {error}
        </div>
      )}

      {displayed.length > 0 ? (
        mode === "ranked" ? (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={handleDragEnd}>
            <SortableContext
              items={displayed.map((j) => j.id)}
              strategy={verticalListSortingStrategy}
            >
              <div
                className={`flex flex-col divide-y divide-border overflow-y-auto overflow-x-hidden max-h-72 min-h-0 ${
                  saving ? "opacity-70" : ""
                }`}
              >
                {displayed.map((job, i) => (
                  <SortableJobRow key={job.id} job={job} rank={i + 1} />
                ))}
              </div>
            </SortableContext>
          </DndContext>
        ) : (
          <div className="flex flex-col divide-y divide-border overflow-y-auto overflow-x-hidden max-h-72 min-h-0">
            {displayed.map((job) => {
              const days = job.days_since_last_activity ?? 0;
              return (
                <Link
                  key={job.id}
                  href={`/jobs/${job.id}`}
                  className="flex items-center gap-3 py-2.5 text-sm transition-colors hover:bg-muted/40 -mx-2 px-2 rounded-md"
                >
                  <div className="min-w-0 flex-1">
                    <span className="block truncate font-medium">{job.title}</span>
                    <span className="block truncate text-muted-foreground">{job.company}</span>
                  </div>
                  <div className="flex w-16 shrink-0 justify-end">
                    <StaleBadge days={days} />
                  </div>
                  <div className="flex flex-col items-end gap-1">
                    <Badge variant="secondary" className="text-xs">
                      {STATUS_LABELS[job.status] ?? job.status}
                    </Badge>
                    <span className="text-xs text-muted-foreground">
                      {days === 0 ? "today" : `${days}d ago`}
                    </span>
                  </div>
                  <ArrowRight className="size-4 shrink-0 text-muted-foreground" />
                </Link>
              );
            })}
          </div>
        )
      ) : (
        <p className="py-6 text-center text-sm text-muted-foreground">
          No active applications yet.
        </p>
      )}
    </div>
  );
}
