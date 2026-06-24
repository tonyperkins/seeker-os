"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Loader2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function RevalidateButton({ resumeId }: { resumeId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleRevalidate() {
    setBusy(true);
    setError(null);
    try {
      await api.resumes.validate(resumeId);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Re-validation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="flex flex-col gap-2">
      <Button variant="outline" size="sm" disabled={busy} onClick={handleRevalidate}>
        {busy ? <Loader2 className="animate-spin" /> : <ShieldCheck />}
        Re-validate
      </Button>
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
    </div>
  );
}
