"use client";

/**
 * Module-level singleton store for tracking in-flight background activities
 * (LLM calls, research, analysis, etc.). Survives client-side navigation
 * because it lives outside React's component lifecycle.
 */

export interface Activity {
  id: string;
  label: string;
  type: "analysis" | "research" | "resume" | "refilter" | "pipeline";
  startedAt: number;
}

type Listener = (activities: Activity[]) => void;

let activities: Activity[] = [];
const listeners = new Set<Listener>();
let counter = 0;

function notify() {
  const snapshot = [...activities];
  listeners.forEach((fn) => fn(snapshot));
}

export function subscribe(listener: Listener): () => void {
  listeners.add(listener);
  listener([...activities]);
  return () => {
    listeners.delete(listener);
  };
}

export function getActivities(): Activity[] {
  return [...activities];
}

export function trackActivity(
  type: Activity["type"],
  label: string,
  promise: Promise<unknown>,
): Promise<unknown> {
  const id = `act-${++counter}`;
  activities = [
    ...activities,
    { id, label, type, startedAt: Date.now() },
  ];
  notify();

  return promise.finally(() => {
    activities = activities.filter((a) => a.id !== id);
    notify();
  });
}

export function useActivityCount(): number {
  // Re-exported for convenience; actual hook lives in the component
  return activities.length;
}
