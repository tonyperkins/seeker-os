"use client";

import { useState } from "react";
import { RefreshCw, Loader2, CheckCircle2, AlertCircle } from "lucide-react";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

export function ReloadConfigButton() {
  const [reloading, setReloading] = useState(false);
  const [result, setResult] = useState<"idle" | "success" | "error">("idle");
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  const handleReload = async () => {
    setReloading(true);
    setResult("idle");
    setErrorMsg(null);
    try {
      await api.settings.reload();
      setResult("success");
      setTimeout(() => setResult("idle"), 3000);
    } catch (e) {
      setResult("error");
      setErrorMsg(e instanceof Error ? e.message : "Failed to reload config");
    } finally {
      setReloading(false);
    }
  };

  return (
    <div className="flex items-center gap-2">
      {result === "success" && (
        <span className="text-xs text-emerald-600 dark:text-emerald-400 flex items-center gap-1">
          <CheckCircle2 className="size-3.5" />
          Config reloaded
        </span>
      )}
      {result === "error" && (
        <span className="text-xs text-destructive flex items-center gap-1">
          <AlertCircle className="size-3.5" />
          {errorMsg}
        </span>
      )}
      <Button
        onClick={handleReload}
        disabled={reloading}
        variant="outline"
        size="sm"
      >
        {reloading ? (
          <Loader2 className="size-4 animate-spin" />
        ) : (
          <RefreshCw className="size-4" />
        )}
        {reloading ? "Reloading..." : "Reload Config"}
      </Button>
    </div>
  );
}
