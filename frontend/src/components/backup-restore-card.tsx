"use client";

import { useState, useRef } from "react";
import {
  Download,
  Upload,
  Loader2,
  AlertCircle,
  CheckCircle2,
  DatabaseBackup,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { api, type RestoreResult } from "@/lib/api";

export function BackupRestoreCard() {
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoreResult, setRestoreResult] = useState<RestoreResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const handleDownload = async () => {
    setDownloading(true);
    setError(null);
    setRestoreResult(null);
    try {
      const blob = await api.backup.download();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `seeker-os-backup-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 15)}.zip`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to download backup");
    } finally {
      setDownloading(false);
    }
  };

  const handleRestore = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setRestoring(true);
    setError(null);
    setRestoreResult(null);
    try {
      const result = await api.backup.restore(file);
      setRestoreResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore backup");
    } finally {
      setRestoring(false);
      if (fileInputRef.current) {
        fileInputRef.current.value = "";
      }
    }
  };

  return (
    <CollapsibleCard
      icon={DatabaseBackup}
      title="Backup & Restore"
      description="Export all configuration files (YAML, .env, master resume) as a zip, or import a previous backup."
    >
      <div className="flex flex-col gap-4">
        {error && (
          <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {restoreResult && (
          <div className="flex items-start gap-2 rounded-md bg-emerald-500/10 p-2.5 text-xs text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-medium">{restoreResult.message}</p>
              {restoreResult.restored.length > 0 && (
                <p className="text-muted-foreground">
                  Files: {restoreResult.restored.join(", ")}
                </p>
              )}
              {restoreResult.skipped.length > 0 && (
                <p className="text-muted-foreground">
                  Skipped: {restoreResult.skipped.join(", ")}
                </p>
              )}
              <p className="text-muted-foreground">
                Reload the page to see restored configuration.
              </p>
            </div>
          </div>
        )}

        <div className="flex flex-wrap items-center gap-3">
          <Button onClick={handleDownload} disabled={downloading} variant="outline">
            {downloading ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
            {downloading ? "Downloading..." : "Download Backup"}
          </Button>

          <Button
            onClick={() => fileInputRef.current?.click()}
            disabled={restoring}
            variant="outline"
          >
            {restoring ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
            {restoring ? "Restoring..." : "Restore from File"}
          </Button>

          <input
            ref={fileInputRef}
            type="file"
            accept=".zip"
            className="hidden"
            onChange={handleRestore}
          />
        </div>

        <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground space-y-1">
          <p className="font-medium text-foreground">What&apos;s included in a backup:</p>
          <ul className="list-disc list-inside space-y-0.5">
            <li>All <code>config/*.yml</code> files and <code>config/blacklist.txt</code></li>
            <li><code>.env</code> (API keys and environment variables)</li>
            <li><code>data/master_resume.*</code> (master resume file)</li>
          </ul>
          <p className="pt-1">
            The SQLite database (<code>data/seeker.db</code>) is not included —
            back it up separately by copying the file or using <code>sqlite3 .dump</code>.
          </p>
        </div>
      </div>
    </CollapsibleCard>
  );
}
