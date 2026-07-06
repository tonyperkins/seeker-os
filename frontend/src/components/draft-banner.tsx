"use client";

import { AlertTriangle } from "lucide-react";

export function DraftBanner({ notice }: { notice?: string | null }) {
  if (!notice) return null;

  return (
    <div className="flex items-start gap-3 rounded-md border border-yellow-500/50 bg-yellow-500/10 p-3">
      <AlertTriangle className="mt-0.5 size-4 shrink-0 text-yellow-600" />
      <div>
        <p className="text-sm font-medium text-yellow-900">Draft — Do Not Submit As-Is</p>
        <p className="text-sm text-yellow-800">{notice}</p>
      </div>
    </div>
  );
}
