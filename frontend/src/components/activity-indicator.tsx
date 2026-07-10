"use client";

import { useEffect, useState } from "react";
import { Loader2, Brain, Building2, FileText, RefreshCw, ChevronDown, ChevronUp } from "lucide-react";
import { subscribe, type Activity } from "@/lib/activity-store";
import { cn } from "@/lib/utils";

const TYPE_ICONS: Record<Activity["type"], typeof Brain> = {
  analysis: Brain,
  research: Building2,
  resume: FileText,
  refilter: RefreshCw,
  pipeline: Loader2,
};

function timeLabel(startedAt: number): string {
  const seconds = Math.floor((Date.now() - startedAt) / 1000);
  if (seconds < 60) return `${seconds}s`;
  const minutes = Math.floor(seconds / 60);
  const rem = seconds % 60;
  return `${minutes}m ${rem}s`;
}

export function ActivityIndicator() {
  const [activities, setActivities] = useState<Activity[]>([]);
  const [expanded, setExpanded] = useState(false);

  useEffect(() => {
    return subscribe(setActivities);
  }, []);

  // Tick every second to update elapsed times
  const [, setTick] = useState(0);
  useEffect(() => {
    if (activities.length === 0) return;
    const interval = setInterval(() => setTick((t) => t + 1), 1000);
    return () => clearInterval(interval);
  }, [activities.length]);

  if (activities.length === 0) return null;

  const visible = expanded ? activities : activities.slice(0, 2);
  const hasMore = activities.length > 2;

  return (
    <div className="border-t border-border px-2 py-2">
      <div className="flex flex-col gap-1">
        <div className="flex items-center gap-1.5 px-1 text-xs font-medium text-muted-foreground">
          <Loader2 className="size-3 animate-spin" />
          <span>
            {activities.length} active{" "}
            {activities.length === 1 ? "task" : "tasks"}
          </span>
        </div>
        <div className="flex flex-col gap-0.5">
          {visible.map((act) => {
            const Icon = TYPE_ICONS[act.type] ?? Loader2;
            return (
              <div
                key={act.id}
                className="flex items-center gap-1.5 rounded-md px-1.5 py-1 text-xs"
                title={act.label}
              >
                <Icon className="size-3 shrink-0 animate-spin text-muted-foreground" />
                <span className="truncate flex-1 text-muted-foreground">
                  {act.label}
                </span>
                <span className="shrink-0 text-[10px] tabular-nums text-muted-foreground/60">
                  {timeLabel(act.startedAt)}
                </span>
              </div>
            );
          })}
        </div>
        {hasMore && (
          <button
            onClick={() => setExpanded(!expanded)}
            className="flex items-center gap-1 px-1.5 text-[10px] text-muted-foreground hover:text-foreground transition-colors"
          >
            {expanded ? (
              <>
                <ChevronUp className="size-3" /> Show less
              </>
            ) : (
              <>
                <ChevronDown className="size-3" /> {activities.length - 2} more
              </>
            )}
          </button>
        )}
      </div>
    </div>
  );
}
