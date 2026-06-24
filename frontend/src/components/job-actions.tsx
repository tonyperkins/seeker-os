"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import {
  XCircle,
  Clock,
  Eye,
  Star,
  Loader2,
  CheckCircle2,
} from "lucide-react";
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
import { Label } from "@/components/ui/label";
import { Input } from "@/components/ui/input";
import { api } from "@/lib/api";

const REJECT_REASONS = [
  "comp_too_low",
  "wrong_seniority",
  "wrong_location",
  "tech_stack_mismatch",
  "not_remote",
  "duplicate",
  "not_relevant",
  "other",
];

export function JobActions({ jobId, currentStatus }: { jobId: number; currentStatus: string }) {
  const router = useRouter();
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [rejectReason, setRejectReason] = useState("");
  const [snoozeDays, setSnoozeDays] = useState("7");
  const [rejectOpen, setRejectOpen] = useState(false);

  async function doAction(
    key: string,
    fn: () => Promise<{ message: string }>,
    refresh = true,
  ) {
    setBusy(key);
    setError(null);
    try {
      await fn();
      if (refresh) router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Action failed");
    } finally {
      setBusy(null);
    }
  }

  return (
    <div className="flex flex-col gap-3">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          {error}
        </div>
      )}
      <div className="flex flex-wrap gap-2">
        {/* Reject with reason dialog */}
        <Dialog open={rejectOpen} onOpenChange={setRejectOpen}>
          <DialogTrigger
            render={
              <Button variant="destructive" disabled={busy !== null}>
                {busy === "reject" ? <Loader2 className="animate-spin" /> : <XCircle />}
                Reject
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Reject job</DialogTitle>
              <DialogDescription>
                Choose a reason. This moves the job to the rejected status.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-3">
              <div className="flex flex-col gap-1.5">
                <Label htmlFor="reject-reason">Reason</Label>
                <select
                  id="reject-reason"
                  value={rejectReason}
                  onChange={(e) => setRejectReason(e.target.value)}
                  className="h-8 rounded-lg border border-input bg-transparent px-2.5 text-sm outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 dark:bg-input/30"
                >
                  <option value="">Select a reason…</option>
                  {REJECT_REASONS.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                variant="destructive"
                disabled={!rejectReason || busy !== null}
                onClick={() =>
                  doAction("reject", () => api.jobs.reject(jobId, rejectReason), true).then(() => {
                    setRejectOpen(false);
                    setRejectReason("");
                  })
                }
              >
                {busy === "reject" ? <Loader2 className="animate-spin" /> : <XCircle />}
                Confirm reject
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        {/* Snooze dialog */}
        <Dialog>
          <DialogTrigger
            render={
              <Button variant="outline" disabled={busy !== null}>
                {busy === "snooze" ? <Loader2 className="animate-spin" /> : <Clock />}
                Snooze
              </Button>
            }
          />
          <DialogContent>
            <DialogHeader>
              <DialogTitle>Snooze job</DialogTitle>
              <DialogDescription>
                Hide this job for a number of days.
              </DialogDescription>
            </DialogHeader>
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="snooze-days">Days</Label>
              <Input
                id="snooze-days"
                type="number"
                min={1}
                max={365}
                value={snoozeDays}
                onChange={(e) => setSnoozeDays(e.target.value)}
              />
            </div>
            <DialogFooter>
              <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
              <Button
                disabled={busy !== null}
                onClick={() =>
                  doAction("snooze", () =>
                    api.jobs.snooze(jobId, parseInt(snoozeDays, 10) || 7),
                  )
                }
              >
                {busy === "snooze" ? <Loader2 className="animate-spin" /> : <Clock />}
                Snooze {snoozeDays}d
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>

        <Button
          variant="outline"
          disabled={busy !== null || currentStatus === "reviewing"}
          onClick={() => doAction("reviewing", () => api.jobs.update(jobId, { status: "reviewing" }))}
        >
          {busy === "reviewing" ? <Loader2 className="animate-spin" /> : <Eye />}
          Mark Reviewing
        </Button>

        <Button
          variant="outline"
          disabled={busy !== null || currentStatus === "interested"}
          onClick={() => doAction("interested", () => api.jobs.update(jobId, { status: "interested" }))}
        >
          {busy === "interested" ? <Loader2 className="animate-spin" /> : <Star />}
          Mark Interested
        </Button>

        {currentStatus !== "ready" && (
          <Button
            variant="ghost"
            disabled={busy !== null}
            onClick={() => doAction("ready", () => api.jobs.update(jobId, { status: "ready" }))}
          >
            {busy === "ready" ? <Loader2 className="animate-spin" /> : <CheckCircle2 />}
            Reset to Ready
          </Button>
        )}
      </div>
    </div>
  );
}
