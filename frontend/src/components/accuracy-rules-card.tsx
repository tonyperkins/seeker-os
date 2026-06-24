"use client";

import { useState, useCallback } from "react";
import {
  ShieldCheck,
  ChevronDown,
  Plus,
  Trash2,
  Loader2,
  Save,
  AlertCircle,
  CheckCircle2,
  Sparkles,
  Wand2,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { api, type AccuracyRule } from "@/lib/api";

const RULE_TYPES: AccuracyRule["type"][] = [
  "disallowed_phrases",
  "forbidden_technologies",
  "required_phrases",
  "experience_anchor",
  "education_omission",
];

const TYPE_LABELS: Record<AccuracyRule["type"], string> = {
  disallowed_phrases: "Disallowed Phrases",
  forbidden_technologies: "Forbidden Technologies",
  required_phrases: "Required Phrases",
  experience_anchor: "Experience Anchor",
  education_omission: "Education Omission",
};

const TYPE_FIELDS: Record<AccuracyRule["type"], "phrases" | "technologies" | "patterns"> = {
  disallowed_phrases: "phrases",
  forbidden_technologies: "technologies",
  required_phrases: "phrases",
  experience_anchor: "patterns",
  education_omission: "patterns",
};

const FIELD_LABELS: Record<string, string> = {
  phrases: "Phrases (comma-separated)",
  technologies: "Technologies (comma-separated)",
  patterns: "Regex Patterns (comma-separated)",
};

const FIELD_PLACEHOLDERS: Record<string, string> = {
  phrases: "expert in, deep expertise, world-class",
  technologies: "ArgoCD, Helm, Rust",
  patterns: "r'(20|30)\\+\\s*years'",
};

export function AccuracyRulesCard({ initialRules }: { initialRules: AccuracyRule[] }) {
  const [open, setOpen] = useState(false);
  const [rules, setRules] = useState<AccuracyRule[]>(initialRules);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [aiText, setAiText] = useState("");
  const [aiGenerating, setAiGenerating] = useState(false);
  const [aiMode, setAiMode] = useState(false);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    setSaved(false);
    try {
      await api.accuracyRules.update({ rules });
      setSaved(true);
      setTimeout(() => setSaved(false), 3000);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save accuracy rules");
    } finally {
      setSaving(false);
    }
  }, [rules]);

  const handleAiGenerate = useCallback(async () => {
    if (!aiText.trim()) return;
    setAiGenerating(true);
    setError(null);
    try {
      const result = await api.accuracyRules.aiGenerate(aiText.trim());
      if (result.rules && result.rules.length > 0) {
        setRules(result.rules);
        setAiMode(false);
        setAiText("");
        setSaved(false);
      } else {
        setError("AI generated no rules. Try rephrasing your description.");
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "AI generation failed");
    } finally {
      setAiGenerating(false);
    }
  }, [aiText]);

  const addRule = () => {
    setRules((prev) => [
      ...prev,
      {
        id: `rule_${Date.now()}`,
        description: "",
        type: "disallowed_phrases",
        severity: "medium",
        phrases: [],
      },
    ]);
  };

  const removeRule = (index: number) => {
    setRules((prev) => prev.filter((_, i) => i !== index));
  };

  const updateRule = (index: number, field: keyof AccuracyRule, value: unknown) => {
    setRules((prev) => prev.map((r, i) => (i === index ? { ...r, [field]: value } : r)));
  };

  const updateRuleList = (index: number, value: string) => {
    const rule = rules[index];
    if (!rule) return;
    const fieldKey = TYPE_FIELDS[rule.type];
    const items = value.split(",").map((s) => s.trim()).filter(Boolean);
    updateRule(index, fieldKey, items);
  };

  const getListValue = (rule: AccuracyRule): string => {
    const fieldKey = TYPE_FIELDS[rule.type];
    const list = rule[fieldKey];
    return Array.isArray(list) ? list.join(", ") : "";
  };

  return (
    <Card>
      <CardHeader
        role="button"
        tabIndex={0}
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        onKeyDown={(e) => {
          if (e.key === "Enter" || e.key === " ") {
            e.preventDefault();
            setOpen((o) => !o);
          }
        }}
        className="flex cursor-pointer select-none flex-row items-start justify-between gap-3"
      >
        <div className="flex min-w-0 flex-col gap-1">
          <CardTitle className="flex items-center gap-2">
            <ShieldCheck className="size-5 shrink-0" />
            Generated Resumes Accuracy Rules
          </CardTitle>
          <CardDescription>
            Rules validated after every resume generation. High severity blocks; medium warns.
            From <code className="text-xs">config/accuracy_rules.yml</code>.
          </CardDescription>
        </div>
        <div className="flex items-center gap-2">
          <Badge variant="outline" className="text-xs">
            {rules.length} {rules.length === 1 ? "rule" : "rules"}
          </Badge>
          <ChevronDown
            className={cn(
              "mt-0.5 size-5 shrink-0 text-muted-foreground transition-transform duration-200",
              open && "rotate-180",
            )}
          />
        </div>
      </CardHeader>
      {open && (
        <CardContent
          className="flex flex-col gap-4"
          onClick={(e) => e.stopPropagation()}
        >
          {error && (
            <div className="flex items-center gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              <AlertCircle className="size-4 shrink-0" />
              <span>{error}</span>
            </div>
          )}

          {saved && (
            <div className="flex items-center gap-2 rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-400">
              <CheckCircle2 className="size-4 shrink-0" />
              <span>Accuracy rules saved.</span>
            </div>
          )}

          {/* AI generation section */}
          <div className="rounded-md border border-border p-3 flex flex-col gap-2">
            <div className="flex items-center justify-between gap-2">
              <div className="flex items-center gap-2 text-sm font-medium">
                <Sparkles className="size-4 text-violet-500" />
                AI Rule Generator
              </div>
              <Button
                size="sm"
                variant="ghost"
                className="h-7 text-xs"
                onClick={() => setAiMode((m) => !m)}
              >
                {aiMode ? "Cancel" : "Describe rules in plain English"}
              </Button>
            </div>
            {aiMode && (
              <div className="flex flex-col gap-2">
                <textarea
                  value={aiText}
                  onChange={(e) => setAiText(e.target.value)}
                  placeholder="e.g. Never claim expertise in AWS, Azure, or GCP. Don't mention my education at DeVry. Always include my LinkedIn URL https://linkedin.com/in/myprofile. Don't use more than 20+ years of experience. Never mention Rust, Helm, or ArgoCD."
                  className="min-h-[80px] w-full rounded-md border border-border bg-background p-3 text-sm resize-y focus:outline-none focus:ring-2 focus:ring-ring"
                  disabled={aiGenerating}
                />
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs text-muted-foreground">
                    The AI will convert your description into structured rules. You can review and edit them before saving.
                  </p>
                  <Button
                    size="sm"
                    onClick={handleAiGenerate}
                    disabled={aiGenerating || !aiText.trim()}
                  >
                    {aiGenerating ? (
                      <Loader2 className="size-3.5 animate-spin" />
                    ) : (
                      <Wand2 className="size-3.5" />
                    )}
                    Generate Rules
                  </Button>
                </div>
              </div>
            )}
          </div>

          {rules.length === 0 ? (
            <p className="py-6 text-center text-sm text-muted-foreground">
              No accuracy rules configured. Add one to enforce constraints on generated resumes.
            </p>
          ) : (
            <div className="flex flex-col gap-3">
              {rules.map((rule, index) => {
                const fieldKey = TYPE_FIELDS[rule.type];
                return (
                  <div
                    key={index}
                    className="flex flex-col gap-2 rounded-md border border-border p-3"
                  >
                    <div className="flex items-center gap-2">
                      <Input
                        value={rule.id}
                        onChange={(e) => updateRule(index, "id", e.target.value)}
                        placeholder="rule_id"
                        className="h-8 font-mono text-xs flex-1"
                      />
                      <select
                        value={rule.severity}
                        onChange={(e) => updateRule(index, "severity", e.target.value)}
                        className="h-8 rounded-md border border-border bg-background px-2 text-xs"
                      >
                        <option value="medium">medium</option>
                        <option value="high">high</option>
                      </select>
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 w-8 p-0 text-muted-foreground hover:text-destructive"
                        onClick={() => removeRule(index)}
                      >
                        <Trash2 className="size-3.5" />
                      </Button>
                    </div>
                    <Input
                      value={rule.description}
                      onChange={(e) => updateRule(index, "description", e.target.value)}
                      placeholder="Description of what this rule enforces"
                      className="h-8 text-xs"
                    />
                    <div className="flex items-center gap-2">
                      <select
                        value={rule.type}
                        onChange={(e) => {
                          const newType = e.target.value as AccuracyRule["type"];
                          const newFieldKey = TYPE_FIELDS[newType];
                          // Clear other field types when switching
                          const updated: AccuracyRule = {
                            ...rule,
                            type: newType,
                            phrases: newFieldKey === "phrases" ? rule.phrases ?? [] : null,
                            technologies: newFieldKey === "technologies" ? rule.technologies ?? [] : null,
                            patterns: newFieldKey === "patterns" ? rule.patterns ?? [] : null,
                          };
                          setRules((prev) => prev.map((r, i) => (i === index ? updated : r)));
                        }}
                        className="h-8 rounded-md border border-border bg-background px-2 text-xs font-mono flex-1"
                      >
                        {RULE_TYPES.map((t) => (
                          <option key={t} value={t}>{TYPE_LABELS[t]}</option>
                        ))}
                      </select>
                    </div>
                    <div className="flex flex-col gap-1">
                      <label className="text-xs text-muted-foreground">
                        {FIELD_LABELS[fieldKey]}
                      </label>
                      <Input
                        value={getListValue(rule)}
                        onChange={(e) => updateRuleList(index, e.target.value)}
                        placeholder={FIELD_PLACEHOLDERS[fieldKey]}
                        className="h-8 font-mono text-xs"
                      />
                    </div>
                  </div>
                );
              })}
            </div>
          )}

          <div className="flex items-center justify-between">
            <Button size="sm" variant="outline" onClick={addRule}>
              <Plus className="size-3.5" />
              Add Rule
            </Button>
            <Button size="sm" onClick={handleSave} disabled={saving}>
              {saving ? <Loader2 className="size-3.5 animate-spin" /> : <Save className="size-3.5" />}
              Save Rules
            </Button>
          </div>
        </CardContent>
      )}
    </Card>
  );
}
