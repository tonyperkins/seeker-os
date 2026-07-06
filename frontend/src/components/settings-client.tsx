"use client";

import { useState, useCallback } from "react";
import { FileText, SlidersHorizontal } from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import { MasterResumeUpload } from "@/components/master-resume-upload";
import { ProfileForm } from "@/components/profile-form";
import { FilterForm } from "@/components/filter-form";
import { type ProfileData, type FiltersData, type ResumeParseResult } from "@/lib/api";
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

  const handleParsed = useCallback((result: ResumeParseResult) => {
    setParseResult(result);
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
            Upload your master resume to get started. After uploading, click &quot;Parse&quot;
            to auto-extract your profile and suggested filter parameters.
          </CardDescription>
        </CardHeader>
        <CardContent>
          <MasterResumeUpload onParsed={handleParsed} bare disabled={demoMode} />
          {parseResult && (
            <div className="mt-4 flex items-start gap-2 rounded-md bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-400">
              <FileText className="mt-0.5 size-4 shrink-0" />
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
        </CardContent>
      </Card>
    );
  }

  // Profile + filters loaded — show the full editing UI
  return (
    <div className="flex flex-col gap-6">
      {/* Master Resume — upload, parse, edit all in one */}
      <CollapsibleCard
        icon={FileText}
        title="Master Resume"
        description="Upload, parse, and edit your master resume. Used for tailored resume generation."
      >
          <MasterResumeUpload onParsed={handleParsed} bare disabled={demoMode} />
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
