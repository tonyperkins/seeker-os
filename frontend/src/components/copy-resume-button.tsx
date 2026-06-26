"use client";

import { useState } from "react";
import { Copy, Check, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function CopyResumeButton({ resumeId }: { resumeId: number }) {
  const [state, setState] = useState<"idle" | "loading" | "copied">("idle");

  async function handleCopy(e: React.MouseEvent) {
    e.stopPropagation();
    setState("loading");
    try {
      const detail = await api.resumes.get(resumeId);
      await navigator.clipboard.writeText(detail.resume_text || "");
      setState("copied");
      setTimeout(() => setState("idle"), 2000);
    } catch {
      setState("idle");
    }
  }

  return (
    <Button
      variant="ghost"
      size="icon"
      onClick={handleCopy}
      className="h-8 w-8 p-0 text-muted-foreground hover:text-foreground"
      title="Copy resume text"
    >
      {state === "loading" ? (
        <Loader2 className="size-3.5 animate-spin" />
      ) : state === "copied" ? (
        <Check className="size-3.5 text-emerald-600" />
      ) : (
        <Copy className="size-3.5" />
      )}
    </Button>
  );
}
