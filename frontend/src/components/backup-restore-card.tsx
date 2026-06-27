"use client";

import { useState, useRef } from "react";
import {
  Download,
  Upload,
  Loader2,
  AlertCircle,
  CheckCircle2,
  DatabaseBackup,
  Database,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Separator } from "@/components/ui/separator";
import { api, type RestoreResult, type MessageResponse } from "@/lib/api";

export function BackupRestoreCard() {
  const [downloading, setDownloading] = useState(false);
  const [restoring, setRestoring] = useState(false);
  const [dbDownloading, setDbDownloading] = useState(false);
  const [dbRestoring, setDbRestoring] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [restoreResult, setRestoreResult] = useState<RestoreResult | null>(null);
  const [dbResult, setDbResult] = useState<MessageResponse | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const dbFileInputRef = useRef<HTMLInputElement>(null);

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

  const handleDbDownload = async () => {
    setDbDownloading(true);
    setError(null);
    setDbResult(null);
    try {
      const blob = await api.backup.downloadDB();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `seeker-os-db-${new Date().toISOString().replace(/[:.]/g, "-").slice(0, 15)}.db`;
      document.body.appendChild(a);
      a.click();
      document.body.removeChild(a);
      URL.revokeObjectURL(url);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to download database");
    } finally {
      setDbDownloading(false);
    }
  };

  const handleDbRestore = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;

    setDbRestoring(true);
    setError(null);
    setDbResult(null);
    try {
      const result = await api.backup.restoreDB(file);
      setDbResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore database");
    } finally {
      setDbRestoring(false);
      if (dbFileInputRef.current) {
        dbFileInputRef.current.value = "";
      }
    }
  };

  return (
    <CollapsibleCard
      icon={DatabaseBackup}
      title="Backup & Restore"
      description="Export and import all configuration files and the database. Safe to run while the server is active."
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

        {dbResult && (
          <div className="flex items-start gap-2 rounded-md bg-emerald-500/10 p-2.5 text-xs text-emerald-700 dark:text-emerald-400">
            <CheckCircle2 className="mt-0.5 size-3.5 shrink-0" />
            <div className="space-y-1">
              <p className="font-medium">{dbResult.message}</p>
              <p className="text-muted-foreground">
                Reload the page to see restored data.
              </p>
            </div>
          </div>
        )}

        {/* Config backup / restore */}
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium">Configuration Files</p>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleDownload} disabled={downloading} variant="outline" size="sm">
              {downloading ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
              {downloading ? "Downloading..." : "Download Config"}
            </Button>

            <Button
              onClick={() => fileInputRef.current?.click()}
              disabled={restoring}
              variant="outline"
              size="sm"
            >
              {restoring ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              {restoring ? "Restoring..." : "Restore Config"}
            </Button>

            <input
              ref={fileInputRef}
              type="file"
              accept=".zip"
              className="hidden"
              onChange={handleRestore}
            />
          </div>
        </div>

        <Separator />

        {/* DB backup / restore */}
        <div className="flex flex-col gap-2">
          <p className="text-sm font-medium flex items-center gap-1.5">
            <Database className="size-4" />
            Database
          </p>
          <div className="flex flex-wrap items-center gap-3">
            <Button onClick={handleDbDownload} disabled={dbDownloading} variant="outline" size="sm">
              {dbDownloading ? <Loader2 className="size-4 animate-spin" /> : <Download className="size-4" />}
              {dbDownloading ? "Downloading..." : "Download DB"}
            </Button>

            <Button
              onClick={() => dbFileInputRef.current?.click()}
              disabled={dbRestoring}
              variant="outline"
              size="sm"
            >
              {dbRestoring ? <Loader2 className="size-4 animate-spin" /> : <Upload className="size-4" />}
              {dbRestoring ? "Restoring..." : "Restore DB"}
            </Button>

            <input
              ref={dbFileInputRef}
              type="file"
              accept=".db,.sqlite,.sqlite3"
              className="hidden"
              onChange={handleDbRestore}
            />
          </div>
        </div>

        <div className="rounded-md bg-muted/50 p-3 text-xs text-muted-foreground space-y-1">
          <p className="font-medium text-foreground">What&apos;s included:</p>
          <ul className="list-disc list-inside space-y-0.5">
            <li><strong>Config backup:</strong> all <code>config/*.yml</code>, <code>blacklist.txt</code>, <code>.env</code>, <code>data/master_resume.*</code></li>
            <li><strong>DB backup:</strong> <code>data/seeker.db</code> (consistent snapshot via SQLite Online Backup API)</li>
          </ul>
          <p className="pt-1">
            Both backup and restore are safe to run while the server is active — no restart required.
          </p>
        </div>
      </div>
    </CollapsibleCard>
  );
}
