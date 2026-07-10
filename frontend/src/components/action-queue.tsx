import Link from "next/link";
import { ArrowRight } from "lucide-react";
import { buttonVariants } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/collapsible-card";
import { ActionQueueRow } from "@/components/action-queue-row";
import type { JobSummary } from "@/lib/api";

export function ActionQueue({ jobs }: { jobs: JobSummary[] }) {
  if (jobs.length === 0) {
    return (
      <CollapsibleCard
        title="Needs Your Decision"
        description="Ready jobs ranked by capped score"
        storageKey="dash-action-queue"
      >
        <p className="py-6 text-center text-sm text-muted-foreground">
          No ready jobs yet. Run the pipeline to discover matches.
        </p>
      </CollapsibleCard>
    );
  }

  return (
    <CollapsibleCard
      title="Needs Your Decision"
      description="Ready jobs ranked by capped score"
      storageKey="dash-action-queue"
      action={
        <Link href="/jobs?status=ready&clear_filters=1" className={buttonVariants({ variant: "ghost", size: "sm" })}>
          View all
          <ArrowRight />
        </Link>
      }
    >
      <div className="flex flex-col divide-y divide-border">
        {jobs.map((job, i) => (
          <ActionQueueRow key={job.id} job={job} rank={i} />
        ))}
      </div>
    </CollapsibleCard>
  );
}
