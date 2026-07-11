"use client";

import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { DeleteButton } from "@/components/delete-button";

export function JobDeleteButton({ jobId }: { jobId: number }) {
  const router = useRouter();

  async function handleDelete() {
    await api.jobs.delete(jobId);
    router.push("/jobs");
    router.refresh();
  }

  return (
    <DeleteButton
      onDelete={handleDelete}
      itemName={`job #${jobId}`}
      itemId={jobId}
      size="sm"
      variant="ghost"
      label="Delete"
      triggerClassName="text-destructive hover:text-destructive"
    />
  );
}
