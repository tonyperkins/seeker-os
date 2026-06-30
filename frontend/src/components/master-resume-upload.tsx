"use client";

import { useState, useEffect, useCallback, useRef } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import {
  Upload,
  FileText,
  CheckCircle2,
  XCircle,
  Loader2,
  RefreshCw,
  Sparkles,
  Pencil,
  Save,
  X,
  Copy,
  Check,
  AlertCircle,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api, type MasterResumeInfo, type ResumeParseResult } from "@/lib/api";
import { cn } from "@/lib/utils";

export function MasterResumeUpload({
  onUploaded,
  onParsed,
  bare = false,
  disabled = false,
}: {
  onUploaded?: () => void;
  onParsed?: (result: ResumeParseResult) => void;
  bare?: boolean;
  disabled?: boolean;
}) {
  const [info, setInfo] = useState<MasterResumeInfo | null>(null);
  const [content, setContent] = useState("");
  const [savedContent, setSavedContent] = useState("");
  const [loading, setLoading] = useState(true);
  const [uploading, setUploading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [parseResult, setParseResult] = useState<ResumeParseResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [parseError, setParseError] = useState<string | null>(null);
  const [dragOver, setDragOver] = useState(false);
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [saved, setSaved] = useState(false);
  const [copied, setCopied] = useState(false);
  const [notMd, setNotMd] = useState(false);

  const loadInfo = useCallback(async () => {
    setError(null);
    try {
      const data = await api.resumes.getMaster();
      setInfo(data);
      setNotMd(data.exists && data.format !== "md");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load master resume info");
    } finally {
      setLoading(false);
    }
  }, []);

  const loadContent = useCallback(async () => {
    try {
      const data = await api.resumes.getMasterContent();
      setContent(data.content);
      setSavedContent(data.content);
      setNotMd(false);
    } catch {
      setNotMd(true);
    }
  }, []);

  const initialized = useRef(false);
  useEffect(() => {
    if (initialized.current) return;
    initialized.current = true;
    loadInfo().then(() => loadContent());
  }, [loadInfo, loadContent]);

  async function handleFile(file: File) {
    if (disabled) return;
    setUploading(true);
    setError(null);
    try {
      const data = await api.resumes.uploadMaster(file);
      setInfo(data);
      setNotMd(data.exists && data.format !== "md");
      onUploaded?.();
      if (data.exists && data.format === "md") {
        await loadContent();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to upload resume");
    } finally {
      setUploading(false);
    }
  }

  function handleInputChange(e: React.ChangeEvent<HTMLInputElement>) {
    if (disabled) return;
    const file = e.target.files?.[0];
    if (file) handleFile(file);
  }

  function handleDrop(e: React.DragEvent) {
    e.preventDefault();
    if (disabled) return;
    setDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) handleFile(file);
  }

  async function handleParse() {
    if (disabled) return;
    setParsing(true);
    setParseError(null);
    try {
      const result = await api.resumes.parse();
      setParseResult(result);
      onParsed?.(result);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Failed to parse resume");
    } finally {
      setParsing(false);
    }
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.resumes.updateMasterContent(content);
      setSavedContent(content);
      setSaved(true);
      setMode("preview");
      setTimeout(() => setSaved(false), 3000);
      loadInfo();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save master resume");
    } finally {
      setSaving(false);
    }
  }

  function handleCancel() {
    setContent(savedContent);
    setMode("preview");
    setError(null);
  }

  const dirty = content !== savedContent;

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

  const inner = (
    <div className="space-y-4">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          {error}
        </div>
      )}

      {/* File info */}
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
        </div>
      )}

      {/* Action buttons */}
      <div className="flex flex-wrap items-center gap-2">
        <label>
          <input
            type="file"
            accept=".md,.docx,.pdf"
            onChange={handleInputChange}
            className="hidden"
            disabled={uploading || disabled}
          />
          <span className={cn(
            "inline-flex items-center gap-2 rounded-md bg-primary px-3 py-1.5 text-xs font-medium text-primary-foreground",
            disabled ? "cursor-not-allowed opacity-50" : "cursor-pointer hover:bg-primary/90",
          )}>
            {uploading ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Upload className="h-3.5 w-3.5" />
            )}
            {uploading ? "Uploading..." : disabled ? "Demo mode" : "Upload"}
          </span>
        </label>
        <Button variant="outline" size="sm" onClick={() => { loadInfo(); loadContent(); }} disabled={loading}>
          <RefreshCw className="h-3.5 w-3.5" />
          Refresh
        </Button>
        <Button variant="outline" size="sm" onClick={handleParse} disabled={parsing || disabled || !info?.exists}>
          {parsing ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <Sparkles className="h-3.5 w-3.5" />}
          {parsing ? "Parsing..." : disabled ? "Demo mode" : "Parse"}
        </Button>
      </div>

      {/* Parse result */}
      {parseError && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
          <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
          <span>{parseError}</span>
        </div>
      )}
      {parseResult && (
        <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
          <p className="font-medium text-emerald-700 dark:text-emerald-400">
            Parsed: {parseResult.contact.name} · {parseResult.current_title} · {parseResult.experience_years} yrs
          </p>
          <div className="mt-1.5 grid gap-0.5 text-muted-foreground">
            <span>Email: {parseResult.contact.email}</span>
            <span>Key skills: {parseResult.key_skills.slice(0, 5).join(", ")}</span>
            <span>Suggested comp floor: ${parseResult.suggested_comp_floor?.toLocaleString()}</span>
          </div>
        </div>
      )}

      {/* Upload drop zone (only when no file exists) */}
      {!info?.exists && (
        <div
          onDragOver={(e) => { if (!disabled) { e.preventDefault(); setDragOver(true); } }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
          className={cn(
            "rounded-lg border-2 border-dashed p-6 text-center transition-colors",
            dragOver && !disabled
              ? "border-primary bg-primary/5"
              : "border-border",
            disabled ? "opacity-50 cursor-not-allowed" : "hover:border-muted-foreground/50",
          )}
        >
          <Upload className="h-6 w-6 text-muted-foreground mx-auto mb-2" />
          <p className="text-sm text-muted-foreground mb-3">
            {disabled ? "Resume upload is disabled in demo mode" : "Drag & drop your master resume here, or use Upload button above"}
          </p>
          <p className="text-xs text-muted-foreground">
            Accepted: .md, .docx, .pdf
          </p>
        </div>
      )}

      {/* Preview / Edit */}
      {info?.exists && (
        <div className="space-y-2">
          {notMd ? (
            <div className="rounded-md border border-border bg-muted/30 p-4 text-center text-sm text-muted-foreground">
              Inline editing is only available for markdown resumes.
              Re-upload as .md to enable the editor.
            </div>
          ) : (
            <>
              <div className="flex items-center justify-end gap-2">
                {saved && (
                  <span className="flex items-center gap-1 text-xs text-emerald-600">
                    <CheckCircle2 className="size-3.5" />
                    Saved
                  </span>
                )}
                {mode === "preview" ? (
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => {
                        navigator.clipboard.writeText(content).then(() => {
                          setCopied(true);
                          setTimeout(() => setCopied(false), 2000);
                        });
                      }}
                    >
                      {copied ? <Check className="size-3.5 text-emerald-600" /> : <Copy className="size-3.5" />}
                      {copied ? "Copied!" : "Copy"}
                    </Button>
                    <Button
                      size="sm"
                      variant="outline"
                      onClick={() => setMode("edit")}
                    >
                      <Pencil className="size-3.5" />
                      Edit
                    </Button>
                  </div>
                ) : (
                  <div className="flex items-center gap-2">
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={handleCancel}
                      disabled={saving}
                    >
                      <X className="size-3.5" />
                      Cancel
                    </Button>
                    <Button
                      size="sm"
                      onClick={handleSave}
                      disabled={saving || !dirty}
                    >
                      {saving ? (
                        <Loader2 className="size-3.5 animate-spin" />
                      ) : (
                        <Save className="size-3.5" />
                      )}
                      Save
                    </Button>
                  </div>
                )}
              </div>

              {mode === "preview" ? (
                <ScrollArea className="h-[500px] rounded-md border border-border bg-background shadow-inner">
                  <div className="resume-preview p-6">
                    <ReactMarkdown remarkPlugins={[remarkGfm]}>
                      {content || "No resume text available."}
                    </ReactMarkdown>
                  </div>
                </ScrollArea>
              ) : (
                <div className="flex flex-col gap-2">
                  <textarea
                    value={content}
                    onChange={(e) => setContent(e.target.value)}
                    className="h-[500px] w-full rounded-md border border-border bg-background p-4 font-mono text-sm leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-ring"
                    placeholder="Edit resume markdown…"
                    disabled={saving}
                  />
                  {dirty && (
                    <p className="text-xs text-amber-600">
                      Unsaved changes — click Save to persist, or Cancel to revert.
                    </p>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  );

  if (bare) {
    return inner;
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
      <CardContent>{inner}</CardContent>
    </Card>
  );
}
