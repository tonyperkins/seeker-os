"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import { Upload, FileText, CheckCircle2, XCircle, Loader2, RefreshCw } from "lucide-react";
import { Card, CardHeader, CardTitle, CardDescription, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { api, type MasterResumeInfo } from "@/lib/api";
import { cn } from "@/lib/utils";

export function MasterResumeUpload({ onUploaded, bare = false }: { onUploaded?: () => void; bare?: boolean }) {
  const [info, setInfo] = useState<MasterResumeInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);

  const loadInfo = useCallback(async () => {
    setError(null);
    try {
      const data = await api.resumes.getMaster();
      setInfo(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load master resume info");
    } finally {
      setLoading(false);
    }
  }, []);

  // Load on mount — use a ref to ensure it only runs once
  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    loadInfo();
  }, [loadInfo]);

  async function handleFile(file: File) {
    setUploading(true);
    setError(null);
    try {
      const data = await api.resumes.uploadMaster(file);
      setInfo(data);
      onUploaded?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to upload resume");
    } finally {
      setUploading(false);
    }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  if (loading) {
    return bare ? (
      <div className="py-10 flex items-center justify-center">
        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
      </div>
    ) : (
      <Card>
        <CardContent className="py-10 flex items-center justify-center">
          <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </CardContent>
      </Card>
    );
  }

  const content = (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          {error}
        </div>
      )}

      {info && (
        <div className="rounded-md border border-border p-3 space-y-2">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              {info.exists ? (
                <CheckCircle2 className="h-4 w-4 text-emerald-500" />
              ) : (
                <XCircle className="h-4 w-4 text-destructive" />
              )}
              <span className="text-sm font-medium">
                {info.exists ? "File exists" : "File not found"}
              </span>
            </div>
            {info.format && (
              <Badge variant="outline" className="uppercase text-xs">
                {info.format}
              </Badge>
            )}
          </div>
          <p className="text-xs text-muted-foreground font-mono break-all">
            {info.path}
          </p>
          {info.exists && info.size_bytes > 0 && (
            <p className="text-xs text-muted-foreground">
              {(info.size_bytes / 1024).toFixed(1)} KB
            </p>
          )}
          {info.text_preview && (
            <pre className="text-xs text-muted-foreground bg-muted/50 rounded p-2 max-h-32 overflow-y-auto whitespace-pre-wrap font-mono">
              {info.text_preview}
            </pre>
          )}
        </div>
      )}

      {/* Upload area */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        className={cn(
          "rounded-lg border-2 border-dashed p-6 text-center transition-colors",
          dragOver
            ? "border-primary bg-primary/5"
            : "border-border hover:border-muted-foreground/50",
        )}
      >
        <Upload className="h-6 w-6 text-muted-foreground mx-auto mb-2" />
        <p className="text-sm text-muted-foreground mb-3">
          Drag &amp; drop your master resume here, or
        </p>
        <label>
          <input
            type="file"
            accept=".md,.docx,.pdf"
            onChange={handleInputChange}
            className="hidden"
            disabled={uploading}
          />
          <span className="inline-flex items-center gap-2 rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground cursor-pointer hover:bg-primary/90">
            {uploading ? (
              <Loader2 className="h-4 w-4 animate-spin" />
            ) : (
              <Upload className="h-4 w-4" />
            )}
            {uploading ? "Uploading..." : "Browse files"}
          </span>
        </label>
        <p className="text-xs text-muted-foreground mt-2">
          Accepted: .md, .docx, .pdf
        </p>
      </div>

      <div className="flex justify-end">
        <Button variant="ghost" size="sm" onClick={loadInfo} disabled={loading}>
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
      </div>
    </div>
  );

  if (bare) {
    return content;
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-base">
          <FileText className="h-4 w-4 text-muted-foreground" />
          Master Resume
        </CardTitle>
        <CardDescription>
          The source resume used for tailored resume generation. Supports .md, .docx, and .pdf.
        </CardDescription>
      </CardHeader>
      <CardContent>{content}</CardContent>
    </Card>
  );
}
