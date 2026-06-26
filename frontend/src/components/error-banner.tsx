"use client";

import { useState } from "react";
import { AlertCircle, FileText, Loader2, Copy, Check } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { api } from "@/lib/api";

/**
 * Reusable error banner with an optional "View server logs" CTA.
 *
 * When `showLogs` is true (default), a button is rendered that opens a dialog
 * showing the tail of the backend log file — useful for diagnosing 500 errors,
 * LLM failures, etc.
 */
export function ErrorBanner({
  message,
  showLogs = true,
}: {
  message: string;
  showLogs?: boolean;
}) {
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [lines, setLines] = useState<string[]>([]);
  const [path, setPath] = useState("");
  const [copied, setCopied] = useState(false);

  async function handleViewLogs() {
    setOpen(true);
    setLoading(true);
    setCopied(false);
    try {
      const res = await api.logs(100);
      setLines(res.lines);
      setPath(res.path);
    } catch {
      setLines(["Failed to load server logs."]);
      setPath("");
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
        <AlertCircle className="size-4 shrink-0" />
        <span className="flex-1">{message}</span>
        {showLogs && (
          <Button
            variant="outline"
            size="sm"
            className="h-6 shrink-0 text-xs"
            onClick={handleViewLogs}
          >
            <FileText className="size-3" />
            View logs
          </Button>
        )}
      </div>

      <Dialog open={open} onOpenChange={setOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Server logs</DialogTitle>
            <DialogDescription>
              {path ? (
                <code className="font-mono text-xs">{path}</code>
              ) : (
                "Loading…"
              )}
            </DialogDescription>
          </DialogHeader>

          <div className="max-h-[50vh] overflow-y-auto rounded-md border border-border bg-muted/30 p-3">
            {loading ? (
              <div className="flex items-center gap-2 text-sm text-muted-foreground">
                <Loader2 className="size-4 animate-spin" />
                Loading logs…
              </div>
            ) : (
              <pre className="whitespace-pre-wrap break-all font-mono text-xs leading-relaxed text-muted-foreground">
                {lines.length > 0 ? lines.join("\n") : "(log file is empty)"}
              </pre>
            )}
          </div>

          <DialogFooter>
            {!loading && lines.length > 0 && (
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  navigator.clipboard.writeText(lines.join("\n")).then(() => {
                    setCopied(true);
                    setTimeout(() => setCopied(false), 2000);
                  });
                }}
              >
                {copied ? (
                  <>
                    <Check className="size-3.5" /> Copied
                  </>
                ) : (
                  <>
                    <Copy className="size-3.5" /> Copy logs
                  </>
                )}
              </Button>
            )}
            <DialogClose render={<Button variant="ghost" size="sm">Close</Button>} />
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
