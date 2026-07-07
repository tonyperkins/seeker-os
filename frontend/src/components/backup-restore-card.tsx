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
  AlertTriangle,
} from "lucide-react";
import { Button } from "@/components/ui/button";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Separator } from "@/components/ui/separator";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
  DialogClose,
} from "@/components/ui/dialog";
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

  // DB restore confirmation state
  const [pendingDbFile, setPendingDbFile] = useState<File | null>(null);
  const [confirmOpen, setConfirmOpen] = useState(false);

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
      // Config was already reloaded server-side during restore;
      // refresh the page data so the UI reflects the new config.
      setTimeout(() => window.location.reload(), 1500);
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

  // When user picks a DB file, open the confirmation dialog instead of restoring immediately
  const handleDbFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    setPendingDbFile(file);
    setConfirmOpen(true);
    // Reset the input so the same file can be re-selected if needed
    if (dbFileInputRef.current) {
      dbFileInputRef.current.value = "";
    }
  };

  const handleDbRestoreConfirmed = async () => {
    if (!pendingDbFile) return;

    setConfirmOpen(false);
    setDbRestoring(true);
    setError(null);
    setDbResult(null);
    try {
      const result = await api.backup.restoreDB(pendingDbFile);
      setDbResult(result);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to restore database");
    } finally {
      setDbRestoring(false);
      setPendingDbFile(null);
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
                Configuration reloaded. Page refreshing...
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
              onChange={handleDbFileSelected}
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
            Both backup and restore are safe to run while the server is active. DB restore
            creates a pre-restore snapshot automatically.
          </p>
        </div>
      </div>

      {/* DB Restore Confirmation Dialog */}
      <Dialog open={confirmOpen} onOpenChange={setConfirmOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="size-5 text-amber-500" />
              Confirm Database Restore
            </DialogTitle>
            <DialogDescription>
              This will <strong>replace all data</strong> in the current database with the
              contents of <code>{pendingDbFile?.name}</code>. Any jobs, analyses, or resumes
              added after this backup was taken will be lost.
              <br /><br />
              A pre-restore snapshot of the current database will be saved automatically
              to <code>data/pre-restore-snapshots/</code> and kept for 7 days.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <DialogClose render={<Button variant="outline" />}>
              Cancel
            </DialogClose>
            <Button
              onClick={handleDbRestoreConfirmed}
              variant="destructive"
            >
              <Database className="size-4" />
              Restore Database
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </CollapsibleCard>
  );
}
