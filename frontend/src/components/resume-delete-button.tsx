"use client";

import { useRouter } from "next/navigation";
import { api } from "@/lib/api";
import { DeleteButton } from "@/components/delete-button";

export function ResumeDeleteButton({
  resumeId,
  resumeLabel,
}: {
  resumeId: number;
  resumeLabel: string;
}) {
  const router = useRouter();

  async function handleDelete() {
    await api.resumes.delete(resumeId);
    router.push("/resumes");
    router.refresh();
  }

  return (
    <DeleteButton
      onDelete={handleDelete}
      itemName={resumeLabel}
      itemId={resumeId}
      size="sm"
      variant="ghost"
      label="Delete"
      triggerClassName="w-full justify-start text-destructive hover:text-destructive"
    />
  );
}
