"use client";

import { useState, useCallback } from "react";
import { useRouter } from "next/navigation";
import { RotateCcw, Loader2, AlertCircle } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function ClearExportsButton({ resumeId }: { resumeId: number }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleClear = useCallback(async () => {
    setBusy(true);
    setError(null);
    try {
      await api.resumes.clearExports(resumeId);
      setOpen(false);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to clear exports");
    } finally {
      setBusy(false);
    }
  }, [resumeId, router]);

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button variant="ghost" size="sm">
            <RotateCcw className="size-3.5" />
            Clear exports
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Clear cached PDF &amp; DOCX?</DialogTitle>
          <DialogDescription>
            This deletes the generated PDF and DOCX files from disk. The markdown
            source is preserved. The next time you download PDF or DOCX, it will
            be regenerated fresh from the markdown.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={busy}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleClear} disabled={busy}>
            {busy ? <Loader2 className="size-4 animate-spin" /> : <RotateCcw className="size-4" />}
            Clear exports
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
