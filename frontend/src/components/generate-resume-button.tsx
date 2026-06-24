"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { FileText, Loader2, CheckCircle2, XCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { api } from "@/lib/api";

export function GenerateResumeButton({ jobId }: { jobId: number }) {
  const router = useRouter();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [result, setResult] = useState<{ resume_id: number; validation_passed: boolean } | null>(null);
  const [open, setOpen] = useState(false);
  const [task, setTask] = useState("resume_generation_standard");

  async function generate() {
    setBusy(true);
    setError(null);
    try {
      const res = await api.resumes.generate(jobId, task);
      const r = res as Record<string, unknown>;
      setResult({
        resume_id: r.resume_id as number,
        validation_passed: r.validation_passed as boolean,
      });
    } catch (err) {
      setError(err instanceof Error ? err.message : "Generation failed");
    } finally {
      setBusy(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger
        render={
          <Button disabled={busy}>
            {busy ? <Loader2 className="animate-spin" /> : <FileText />}
            Generate Resume
          </Button>
        }
      />
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Generate tailored resume</DialogTitle>
          <DialogDescription>
            This will use the LLM to tailor your master resume for this job.
            The result is validated against your accuracy rules.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            {error}
          </div>
        )}

        {result ? (
          <div className="flex flex-col gap-2">
            <div className="flex items-center gap-2 text-sm">
              {result.validation_passed ? (
                <><CheckCircle2 className="h-4 w-4 text-green-500" /> Resume generated and validated</>
              ) : (
                <><XCircle className="h-4 w-4 text-destructive" /> Resume generated with validation violations</>
              )}
            </div>
            <Button
              onClick={() => router.push(`/resumes/${result.resume_id}`)}
            >
              View resume →
            </Button>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <div className="flex flex-col gap-1.5">
              <label className="text-sm font-medium">Model tier</label>
              <select
                value={task}
                onChange={(e) => setTask(e.target.value)}
                className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
              >
                <option value="resume_generation_standard">Standard (Sonnet)</option>
                <option value="resume_generation_high_value">High Value (Opus)</option>
              </select>
            </div>
          </div>
        )}

        <DialogFooter>
          {!result && (
            <>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button disabled={busy} onClick={generate}>
                {busy ? <Loader2 className="animate-spin" /> : <FileText />}
                Generate
              </Button>
            </>
          )}
          {result && (
            <DialogClose render={<Button />}>Done</DialogClose>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
