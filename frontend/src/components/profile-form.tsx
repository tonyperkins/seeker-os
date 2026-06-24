"use client";

import { useState, useEffect, useRef } from "react";
import { User, DollarSign, Briefcase, MapPin, MessageSquare, Save, Loader2, CheckCircle2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import { api, type ProfileData, type ResumeParseResult } from "@/lib/api";

export function ProfileForm({
  profile,
  parseResult,
  onSaved,
}: {
  profile: ProfileData;
  parseResult?: ResumeParseResult | null;
  onSaved?: () => void;
}) {
  const [form, setForm] = useState<ProfileData>(profile);
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
        contact: {
          ...prev.contact,
          name: parseResult.contact.name || prev.contact.name,
          email: parseResult.contact.email || prev.contact.email,
          phone: parseResult.contact.phone || prev.contact.phone,
          location: parseResult.contact.location || prev.contact.location,
          urls: { ...prev.contact.urls, ...parseResult.contact.urls },
        },
        user: {
          ...prev.user,
          name: parseResult.contact.name || prev.user.name,
          email: parseResult.contact.email || prev.user.email,
          location: parseResult.contact.location || prev.user.location,
        },
        experience: {
          ...prev.experience,
          years: parseResult.experience_years ?? prev.experience.years,
        },
        instructions: prev.instructions || parseResult.summary || "",
      }));
    }
  }, [parseResult]);

  function update<K extends keyof ProfileData>(key: K, value: ProfileData[K]) {
    setForm((prev) => ({ ...prev, [key]: value }));
    setSaved(false);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      await api.profile.update(form);
      setSaved(true);
      onSaved?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save profile");
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      {error && (
        <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">{error}</div>
      )}

      {/* Contact Info */}
      <Section icon={User} title="Contact Information">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Full Name">
            <Input value={form.contact.name} onChange={(e) => update("contact", { ...form.contact, name: e.target.value })} />
          </Field>
          <Field label="Email">
            <Input type="email" value={form.contact.email} onChange={(e) => update("contact", { ...form.contact, email: e.target.value })} />
          </Field>
          <Field label="Phone">
            <Input value={form.contact.phone} onChange={(e) => update("contact", { ...form.contact, phone: e.target.value })} />
          </Field>
          <Field label="Location">
            <Input value={form.contact.location} onChange={(e) => update("contact", { ...form.contact, location: e.target.value })} placeholder="City, ST" />
          </Field>
        </div>
        <div className="grid gap-3 sm:grid-cols-2 mt-3">
          <Field label="GitHub URL">
            <Input value={form.contact.urls.github || ""} onChange={(e) => update("contact", { ...form.contact, urls: { ...form.contact.urls, github: e.target.value } })} placeholder="https://github.com/..." />
          </Field>
          <Field label="LinkedIn URL">
            <Input value={form.contact.urls.linkedin || ""} onChange={(e) => update("contact", { ...form.contact, urls: { ...form.contact.urls, linkedin: e.target.value } })} placeholder="https://linkedin.com/in/..." />
          </Field>
          <Field label="Portfolio URL">
            <Input value={form.contact.urls.portfolio || ""} onChange={(e) => update("contact", { ...form.contact, urls: { ...form.contact.urls, portfolio: e.target.value } })} placeholder="https://..." />
          </Field>
          <Field label="Other URL">
            <Input value={form.contact.urls.other || ""} onChange={(e) => update("contact", { ...form.contact, urls: { ...form.contact.urls, other: e.target.value } })} placeholder="https://..." />
          </Field>
        </div>
      </Section>

      {/* Compensation */}
      <Section icon={DollarSign} title="Compensation">
        <div className="grid gap-3 sm:grid-cols-3">
          <Field label="Floor (USD)">
            <Input type="number" value={form.comp.floor} onChange={(e) => update("comp", { ...form.comp, floor: parseInt(e.target.value) || 0 })} />
          </Field>
          <Field label="Target (USD)">
            <Input type="number" value={form.comp.target} onChange={(e) => update("comp", { ...form.comp, target: parseInt(e.target.value) || 0 })} />
          </Field>
          <Field label="Stretch (USD)">
            <Input type="number" value={form.comp.stretch} onChange={(e) => update("comp", { ...form.comp, stretch: parseInt(e.target.value) || 0 })} />
          </Field>
        </div>
      </Section>

      {/* Experience & Employment */}
      <Section icon={Briefcase} title="Experience & Employment">
        <div className="grid gap-3 sm:grid-cols-2">
          <Field label="Years of Experience">
            <Input type="number" value={form.experience.years} onChange={(e) => update("experience", { ...form.experience, years: parseInt(e.target.value) || 0 })} />
          </Field>
          <Field label="Anchor Phrase">
            <Input value={form.experience.anchor_phrase} onChange={(e) => update("experience", { ...form.experience, anchor_phrase: e.target.value })} placeholder="25+ years" />
          </Field>
          <Field label="Commitment">
            <Input value={form.employment.commitment} onChange={(e) => update("employment", { ...form.employment, commitment: e.target.value })} />
          </Field>
          <Field label="Role Type">
            <Input value={form.employment.role_type} onChange={(e) => update("employment", { ...form.employment, role_type: e.target.value })} />
          </Field>
        </div>
      </Section>

      {/* Blacklist */}
      <Section icon={MapPin} title="Company Blacklist">
        <TagInput
          values={form.blacklist}
          onChange={(values) => update("blacklist", values)}
          placeholder="Add company name..."
        />
      </Section>

      {/* Instructions */}
      <Section icon={MessageSquare} title="Free-form Instructions">
        <Field label="Instructions for scoring & resume generation">
          <Textarea
            value={form.instructions}
            onChange={(e) => update("instructions", e.target.value)}
            rows={4}
            placeholder="E.g. 'I prefer Go over Python', 'Don't highlight my time at defense contractors', 'I'm targeting staff-level platform roles, not pure SRE'..."
          />
        </Field>
        <p className="text-xs text-muted-foreground mt-1">
          These instructions are injected into the system prompt for job scoring and resume generation.
        </p>
      </Section>

      {/* Save */}
      <div className="flex items-center gap-3">
        <Button onClick={handleSave} disabled={saving}>
          {saving ? <Loader2 className="animate-spin" /> : saved ? <CheckCircle2 /> : <Save />}
          {saving ? "Saving..." : saved ? "Saved!" : "Save Profile"}
        </Button>
      </div>
    </div>
  );
}

function Section({ icon: Icon, title, children }: { icon: React.ComponentType<{ className?: string }>; title: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-3">
      <div className="flex items-center gap-2 text-sm font-medium">
        <Icon className="size-4 text-muted-foreground" />
        {title}
      </div>
      {children}
    </div>
  );
}

function Field({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex flex-col gap-1.5">
      <Label className="text-xs text-muted-foreground">{label}</Label>
      {children}
    </div>
  );
}

function TagInput({ values, onChange, placeholder }: { values: string[]; onChange: (values: string[]) => void; placeholder?: string }) {
  const [input, setInput] = useState("");

  function add() {
    const v = input.trim();
    if (v && !values.includes(v)) {
      onChange([...values, v]);
    }
    setInput("");
  }

  return (
    <div className="flex flex-col gap-2">
      <div className="flex gap-2">
        <Input
          value={input}
          onChange={(e) => setInput(e.target.value)}
          onKeyDown={(e) => e.key === "Enter" && (e.preventDefault(), add())}
          placeholder={placeholder}
          className="flex-1"
        />
        <Button size="sm" variant="outline" onClick={add} disabled={!input.trim()}>Add</Button>
      </div>
      {values.length > 0 && (
        <div className="flex flex-wrap gap-1.5">
          {values.map((v) => (
            <span key={v} className="inline-flex items-center gap-1 rounded-md bg-muted px-2 py-1 text-xs">
              {v}
              <button
                onClick={() => onChange(values.filter((x) => x !== v))}
                className="text-muted-foreground hover:text-destructive"
              >
                ×
              </button>
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
