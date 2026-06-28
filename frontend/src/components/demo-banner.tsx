"use client";

import { useDemoMode } from "@/lib/demo";

export function DemoBanner() {
  const { demoMode, loading } = useDemoMode();

  if (loading || !demoMode) return null;

  return (
    <div className="bg-amber-500 text-amber-950 px-4 py-2 text-sm font-medium text-center">
      Demo mode: read-only synthetic data. Runs, edits, uploads, and settings
      changes are disabled.
    </div>
  );
}
