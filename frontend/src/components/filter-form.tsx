"use client";

import { useState, useEffect, useRef } from "react";
import { Save, Loader2, CheckCircle2, Plus, X } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type FiltersData, type ResumeParseResult } from "@/lib/api";

export function FilterForm({
  filters,
  parseResult,
  onSaved,
  disabled = false,
}: {
  filters: FiltersData;
  parseResult?: ResumeParseResult | null;
  onSaved?: () => void;
  disabled?: boolean;
}) {
  const [form, setForm] = useState<FiltersData>(filters);
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const initialized = useRef(false);

  // Pre-fill from parse result when available
  useEffect(() => {
    if (parseResult && !initialized.current) {
      initialized.current = true;
      setForm((prev) => ({
        ...prev,
        title_filters: {
          ...prev.title_filters,
          positive: parseResult.suggested_title_positive.length > 0
            ? Array.from(new Set([...prev.title_filters.positive, ...parseResult.suggested_title_positive]))
            : prev.title_filters.positive,
        },
      }));
    }
  }, [parseResult]);

  function updateFilters(patch: Partial<FiltersData["filters"]>) {
    setForm((prev) => ({ ...prev, filters: { ...prev.filters, ...patch } }));
    setSaved(false);
  }

  function updateTitleFilters(patch: Partial<FiltersData["title_filters"]>) {
    setForm((prev) => ({ ...prev, title_filters: { ...prev.title_filters, ...patch } }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.filters.update(form);
      setSaved(true);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save filters");
    } finally {
      setSaving(false);
    }
  }

  const f = form.filters;

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">{error}</div>
      )}

      {/* Toggles */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Toggle
          label="Remote Only"
          checked={f.remote_only}
          onChange={(v) => updateFilters({ remote_only: v })}
        />
        <Toggle
          label="US Only"
          checked={f.us_only}
          onChange={(v) => updateFilters({ us_only: v })}
        />
        <Toggle
          label="Comp Unknown Passes"
          checked={f.comp_unknown_passes}
          onChange={(v) => updateFilters({ comp_unknown_passes: v })}
        />
        <Toggle
          label="Visa Sponsorship Required"
          checked={f.visa_sponsorship_required}
          onChange={(v) => updateFilters({ visa_sponsorship_required: v })}
        />
      </div>

      {/* Comp Floor Margin */}
      <div className="flex flex-col gap-1.5">
        <Label className="text-xs text-muted-foreground">Comp Floor Margin (%)</Label>
        <div className="flex items-center gap-2">
          <input
            type="range"
            min={0}
            max={20}
            value={f.comp_floor_margin_pct}
            onChange={(e) => updateFilters({ comp_floor_margin_pct: parseInt(e.target.value) })}
            className="flex-1"
          />
          <span className="font-mono text-sm w-10 text-right">{f.comp_floor_margin_pct}%</span>
        </div>
        <p className="text-xs text-muted-foreground">
          Applied as tolerance below profile.comp.floor (set in Profile settings).
        </p>
      </div>

      {/* Freshness + Commitment */}
      <div className="grid gap-3 sm:grid-cols-2">
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Freshness (days)</Label>
          <Input
            type="number"
            value={f.freshness_days}
            onChange={(e) => updateFilters({ freshness_days: parseInt(e.target.value) || 0 })}
          />
        </div>
        <div className="flex flex-col gap-1.5">
          <Label className="text-xs text-muted-foreground">Commitment Required</Label>
          <select
            value={f.commitment_required}
            onChange={(e) => updateFilters({ commitment_required: e.target.value })}
            className="h-9 rounded-md border border-input bg-background px-3 text-sm text-foreground"
          >
            <option value="Full Time" className="bg-background text-foreground">Full Time</option>
            <option value="Part Time" className="bg-background text-foreground">Part Time</option>
            <option value="Contract" className="bg-background text-foreground">Contract</option>
            <option value="" className="bg-background text-foreground">Any</option>
          </select>
        </div>
      </div>

      {/* Seniority */}
      <div className="flex flex-col gap-3">
        <span className="text-sm font-medium">Seniority</span>
        <div className="grid gap-3 sm:grid-cols-3">
          <TagInputField
            label="Floor (accept these)"
            values={f.seniority_floor}
            onChange={(values) => updateFilters({ seniority_floor: values })}
            placeholder="Senior Level"
          />
          <TagInputField
            label="Reject these"
            values={f.seniority_reject}
            onChange={(values) => updateFilters({ seniority_reject: values })}
            placeholder="Mid Level"
          />
          <TagInputField
            label="Title Override (pass regardless of tag)"
            values={f.seniority_title_override}
            onChange={(values) => updateFilters({ seniority_title_override: values })}
            placeholder="senior, staff, principal"
          />
        </div>
        <Toggle
          label="Unknown seniority passes"
          checked={f.seniority_unknown_passes}
          onChange={(v) => updateFilters({ seniority_unknown_passes: v })}
        />
      </div>

      {/* Location Exclude */}
      <TagInputField
        label="Location Exclude (states/cities)"
        values={f.location_exclude}
        onChange={(values) => updateFilters({ location_exclude: values })}
        placeholder="new york, california..."
      />

      {/* Title Filters */}
      <div className="flex flex-col gap-3">
        <span className="text-sm font-medium">Title Patterns</span>
        <TagInputField
          label="Positive (must match at least one)"
          values={form.title_filters.positive}
          onChange={(values) => updateTitleFilters({ positive: values })}
          placeholder="sre, devops, platform engineer..."
        />
        <TagInputField
          label="Negative (reject if matched)"
          values={form.title_filters.negative}
          onChange={(values) => updateTitleFilters({ negative: values })}
          placeholder="manager, director, frontend..."
        />
      </div>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving || disabled}>
          {saving ? <Loader2 className="animate-spin" /> : saved ? <CheckCircle2 /> : <Save />}
          {saving ? "Saving..." : disabled ? "Demo mode" : saved ? "Saved!" : "Save Filters"}
        </Button>
      </div>
    </div>
  );
}

function Toggle({ label, checked, onChange }: { label: string; checked: boolean; onChange: (_v: boolean) => void }) {
  return (
    <label className="flex items-center gap-2 rounded-md border border-border p-3 cursor-pointer hover:bg-muted/50 transition-colors">
      <input
        type="checkbox"
        checked={checked}
        onChange={(e) => onChange(e.target.checked)}
        className="size-4 rounded border-border"
      />
      <span className="text-sm">{label}</span>
    </label>
  );
}

function TagInputField({ label, values, onChange, placeholder }: { label: string; values: string[]; onChange: (_values: string[]) => void; placeholder?: string }) {
  const [input, setInput] = useState("");

  function add() {
    const v = input.trim().toLowerCase();
    if (v && !values.includes(v)) {
      onChange([...values, v]);
    }
    setInput("");
  }

  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      <div className="flex gap-1.5">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
          placeholder={placeholder}
          className="flex-1 text-sm"
        />
        <Button size="sm" variant="outline" onClick={add} disabled={!input.trim()}>
          <Plus className="size-3" />
        </Button>
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1">
          {values.map((v) => (
            <span key={v} className="inline-flex items-center gap-1 rounded bg-muted px-2 py-0.5 text-xs font-mono">
              {v}
              <button
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="text-muted-foreground hover:text-destructive"
              >
                <X className="size-3" />
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
