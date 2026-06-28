"use client";

import { useState, useCallback } from "react";
import { Sparkles, Loader2, FileText, SlidersHorizontal, AlertCircle, CheckCircle2 } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { Button } from "@/components/ui/button";
import { MasterResumeUpload } from "@/components/master-resume-upload";
import { ProfileForm } from "@/components/profile-form";
import { FilterForm } from "@/components/filter-form";
import { api, type ProfileData, type FiltersData, type ResumeParseResult } from "@/lib/api";
import { useDemoMode } from "@/lib/demo";

export function SettingsClient({
  profile: initialProfile,
  filters: initialFilters,
}: {
  profile: ProfileData | null;
  filters: FiltersData | null;
}) {
  const { demoMode } = useDemoMode();
  const [parseResult, setParseResult] = useState<ResumeParseResult | null>(null);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [resumeUploaded, setResumeUploaded] = useState(false);

  const handleParse = useCallback(async () => {
    setParsing(true);
    setParseError(null);
    try {
      const result = await api.resumes.parse();
      setParseResult(result);
    } catch (e) {
      setParseError(e instanceof Error ? e.message : "Failed to parse resume");
    } finally {
      setParsing(false);
    }
  }, []);

  // If no profile or filters loaded, show upload + parse only
  if (!initialProfile || !initialFilters) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <FileText className="size-5" />
            Resume Setup
          </CardTitle>
          <CardDescription>
            Upload your master resume to get started. After uploading, click &quot;Parse Resume&quot;
            to auto-extract your profile and suggested filter parameters.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MasterResumeUpload onUploaded={() => setResumeUploaded(true)} bare disabled={demoMode} />
          {resumeUploaded && (
            <div className="mt-4 flex flex-col gap-3">
              <Button onClick={handleParse} disabled={parsing || demoMode} size="lg">
                {parsing ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {parsing ? "Parsing Resume..." : demoMode ? "Demo mode" : "Parse Resume"}
              </Button>
              {parseError && (
                <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                  <AlertCircle className="mt-0.5 size-4 shrink-0" />
                  <span>{parseError}</span>
                </div>
              )}
              {parseResult && (
                <div className="flex items-start gap-2 rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-400">
                  <CheckCircle2 className="mt-0.5 size-4 shrink-0" />
                  <div className="space-y-1">
                    <p className="font-medium">Resume parsed successfully!</p>
                    <p className="text-xs">
                      {parseResult.contact.name} · {parseResult.current_title} ·{" "}
                      {parseResult.experience_years} years experience
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Reload the page to see the pre-filled profile and filter forms.
                    </p>
                  </div>
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    );
  }

  // Profile + filters loaded — show the full editing UI
  return (
    <div className="flex flex-col gap-6">
      {/* Resume Upload + Parse */}
      <CollapsibleCard
        icon={FileText}
        title="Master Resume"
        description="Upload your master resume. Click &quot;Parse&quot; to auto-extract contact info, experience, and suggested filter parameters."
      >
          <div className="flex flex-col gap-4">
            <MasterResumeUpload onUploaded={() => setResumeUploaded(true)} bare disabled={demoMode} />
            <div className="flex items-center gap-3">
              <Button onClick={handleParse} disabled={parsing || demoMode} variant="outline">
                {parsing ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {parsing ? "Parsing..." : demoMode ? "Demo mode" : "Parse Resume"}
              </Button>
              {parseResult && (
                <span className="text-xs text-muted-foreground">
                  Parsed: {parseResult.contact.name} · {parseResult.current_title}
                </span>
              )}
            </div>
            {parseError && (
              <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
                <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
                <span>{parseError}</span>
              </div>
            )}
            {parseResult && (
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-3 text-xs">
                <p className="font-medium text-emerald-700 dark:text-emerald-400">
                  Extracted data — review and edit below:
                </p>
                <div className="mt-1.5 grid gap-1 text-muted-foreground">
                  <span>Name: {parseResult.contact.name}</span>
                  <span>Email: {parseResult.contact.email}</span>
                  <span>Experience: {parseResult.experience_years} years</span>
                  <span>Current title: {parseResult.current_title}</span>
                  <span>Key skills: {parseResult.key_skills.slice(0, 5).join(", ")}</span>
                  <span>Suggested comp floor: ${parseResult.suggested_comp_floor?.toLocaleString()}</span>
                </div>
              </div>
            )}
          </div>
      </CollapsibleCard>

      {/* Profile Form */}
      <CollapsibleCard
        icon={FileText}
        title="Profile"
        description="Contact info, compensation, experience, and free-form instructions for scoring and resume generation."
      >
          <ProfileForm
            key={parseResult ? `parsed-${parseResult.contact.name}` : "initial"}
            profile={initialProfile}
            parseResult={parseResult}
            disabled={demoMode}
          />
      </CollapsibleCard>

      {/* Filter Form */}
      <CollapsibleCard
        icon={SlidersHorizontal}
        title="Filter Parameters"
        description="Tier-2 hard filters applied before JD fetch. Title patterns, seniority, comp, freshness, and more."
      >
          <FilterForm
            key={parseResult ? `parsed-${parseResult.suggested_comp_floor}` : "initial"}
            filters={initialFilters}
            parseResult={parseResult}
            disabled={demoMode}
          />
      </CollapsibleCard>
    </div>
  );
}
