"use client";

import { useState, useCallback } from "react";
import ReactMarkdown from "react-markdown";
import {
  Pencil,
  Save,
  X,
  Loader2,
  CheckCircle2,
  AlertCircle,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardAction,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { ScrollArea } from "@/components/ui/scroll-area";
import { api } from "@/lib/api";

export function ResumeEditor({
  resumeId,
  initialText,
}: {
  resumeId: number;
  initialText: string;
}) {
  const [mode, setMode] = useState<"preview" | "edit">("preview");
  const [text, setText] = useState(initialText);
  const [savedText, setSavedText] = useState(initialText);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const dirty = text !== savedText;

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.resumes.update(resumeId, text);
      setSavedText(text);
      setSaved(true);
      setMode("preview");
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save resume");
    } finally {
      setSaving(false);
    }
  }, [resumeId, text]);

  const handleCancel = () => {
    setText(savedText);
    setMode("preview");
    setError(null);
  };

  return (
    <Card>
      <CardHeader>
        <CardTitle>Resume Text</CardTitle>
        <CardDescription>
          {mode === "preview" ? "Rendered markdown preview" : "Edit markdown directly"}
        </CardDescription>
        <CardAction>
          <div className="flex items-center gap-2">
            {saved && (
              <span className="flex items-center gap-1 text-xs text-emerald-600">
                <CheckCircle2 className="size-3.5" />
                Saved
              </span>
            )}
            {mode === "preview" ? (
              <Button
                size="sm"
                variant="outline"
                onClick={() => setMode("edit")}
              >
                <Pencil className="size-3.5" />
                Edit
              </Button>
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
        </CardAction>
      </CardHeader>
      <CardContent>
        {error && (
          <div className="mb-3 flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
            <AlertCircle className="size-4 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {mode === "preview" ? (
          <ScrollArea className="h-[600px] rounded-md border border-border p-6">
            <div className="prose prose-sm dark:prose-invert max-w-none">
              <ReactMarkdown>{text || "No resume text available."}</ReactMarkdown>
            </div>
          </ScrollArea>
        ) : (
          <div className="flex flex-col gap-2">
            <textarea
              value={text}
              onChange={(e) => setText(e.target.value)}
              className="h-[600px] w-full rounded-md border border-border bg-background p-4 font-mono text-sm leading-relaxed resize-none focus:outline-none focus:ring-2 focus:ring-ring"
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
      </CardContent>
    </Card>
  );
}
