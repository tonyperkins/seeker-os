"use client";

import { useEffect, useState, useCallback } from "react";
import Link from "next/link";
import {
  Loader2,
  AlertCircle,
  CheckCircle2,
  Eye,
  Star,
  Send,
  XCircle,
  GripVertical,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { api, type JobSummary } from "@/lib/api";

const COLUMNS = [
  { key: "ready", label: "Ready", icon: CheckCircle2, color: "text-emerald-500" },
  { key: "reviewing", label: "Reviewing", icon: Eye, color: "text-blue-500" },
  { key: "interested", label: "Interested", icon: Star, color: "text-amber-500" },
  { key: "applied", label: "Applied", icon: Send, color: "text-purple-500" },
  { key: "rejected", label: "Rejected", icon: XCircle, color: "text-destructive" },
] as const;

export default function KanbanPage() {
  const [jobs, setJobs] = useState<JobSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [dragId, setDragId] = useState<number | null>(null);
  const [dragOverCol, setDragOverCol] = useState<string | null>(null);
  const [updatingId, setUpdatingId] = useState<number | null>(null);

  const fetchJobs = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      // Fetch jobs across all kanban-relevant statuses
      const data = await api.jobs.list({ limit: 500 });
      setJobs(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to load jobs");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    // Fetch board on mount — legitimate data-fetching effect.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    fetchJobs();
  }, [fetchJobs]);

  const jobsByColumn = (colKey: string): JobSummary[] => {
    if (!jobs) return [];
    return jobs
      .filter((j) => j.status === colKey)
      .sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  };

  function handleDragStart(e: React.DragEvent, id: number) {
    setDragId(id);
    e.dataTransfer.effectAllowed = "move";
    e.dataTransfer.setData("text/plain", String(id));
  }

  function handleDragOver(e: React.DragEvent, colKey: string) {
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    if (dragOverCol !== colKey) setDragOverCol(colKey);
  }

  function handleDragLeave(_e: React.DragEvent, colKey: string) {
    if (dragOverCol === colKey) setDragOverCol(null);
  }

  async function handleDrop(e: React.DragEvent, colKey: string) {
    e.preventDefault();
    setDragOverCol(null);
    const id = Number(e.dataTransfer.getData("text/plain"));
    setDragId(null);
    if (!id) return;

    const job = jobs?.find((j) => j.id === id);
    if (!job || job.status === colKey) return;

    // Optimistic update
    setJobs((prev) =>
      prev ? prev.map((j) => (j.id === id ? { ...j, status: colKey } : j)) : prev,
    );

    setUpdatingId(id);
    try {
      await api.jobs.update(id, { status: colKey });
    } catch (err) {
      // Revert on failure
      setJobs((prev) =>
        prev ? prev.map((j) => (j.id === id ? { ...j, status: job.status } : j)) : prev,
      );
      setError(err instanceof Error ? err.message : "Failed to update status");
    } finally {
      setUpdatingId(null);
    }
  }

  if (loading) {
    return (
      <div className="flex items-center justify-center gap-2 py-20 text-sm text-muted-foreground">
        <Loader2 className="animate-spin" />
        Loading board…
      </div>
    );
  }

  if (error && !jobs) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight">Kanban</h1>
        <Card>
          <CardContent className="flex items-center gap-2 py-10 text-destructive">
            <AlertCircle className="size-4" />
            {error}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Kanban</h1>
          <p className="text-sm text-muted-foreground">
            Drag and drop jobs between columns to update status.
          </p>
        </div>
        {error && (
          <span className="text-xs text-destructive">{error}</span>
        )}
      </div>

      <div className="grid grid-cols-1 gap-4 md:grid-cols-3 lg:grid-cols-5">
        {COLUMNS.map((col) => {
          const Icon = col.icon;
          const colJobs = jobsByColumn(col.key);
          return (
            <div
              key={col.key}
              className={`flex flex-col gap-2 rounded-xl border p-2 transition-colors ${
                dragOverCol === col.key
                  ? "border-primary bg-primary/5"
                  : "border-border bg-muted/20"
              }`}
              onDragOver={(e) => handleDragOver(e, col.key)}
              onDragLeave={(e) => handleDragLeave(e, col.key)}
              onDrop={(e) => handleDrop(e, col.key)}
            >
              <div className="flex items-center gap-2 px-1 py-1">
                <Icon className={`size-4 ${col.color}`} />
                <span className="text-sm font-semibold">{col.label}</span>
                <Badge variant="secondary" className="ml-auto">
                  {colJobs.length}
                </Badge>
              </div>

              <div className="flex flex-col gap-2 min-h-[120px]">
                {colJobs.length === 0 ? (
                  <div className="flex items-center justify-center rounded-md border border-dashed border-border/60 py-8 text-xs text-muted-foreground">
                    Drop here
                  </div>
                ) : (
                  colJobs.map((job) => (
                    <Card
                      key={job.id}
                      size="sm"
                      draggable
                      onDragStart={(e) => handleDragStart(e, job.id)}
                      className={`cursor-grab active:cursor-grabbing transition-opacity ${
                        dragId === job.id ? "opacity-40" : ""
                      }`}
                    >
                      <CardHeader className="gap-1">
                        <div className="flex items-start gap-1.5">
                          <GripVertical className="mt-0.5 size-3.5 shrink-0 text-muted-foreground/60" />
                          <Link
                            href={`/jobs/${job.id}`}
                            className="text-sm font-medium leading-snug hover:underline"
                            onClick={(e) => e.stopPropagation()}
                          >
                            {job.title}
                          </Link>
                        </div>
                        <CardDescription className="pl-5">
                          {job.company}
                        </CardDescription>
                      </CardHeader>
                      <CardContent className="flex items-center gap-2 pl-5">
                        {job.score != null && (
                          <Badge variant="default" className="text-xs">
                            {job.score}
                          </Badge>
                        )}
                        {job.is_pinned && (
                          <span className="text-xs text-amber-500">pinned</span>
                        )}
                        {updatingId === job.id && (
                          <Loader2 className="ml-auto size-3.5 animate-spin text-muted-foreground" />
                        )}
                      </CardContent>
                    </Card>
                  ))
                )}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
