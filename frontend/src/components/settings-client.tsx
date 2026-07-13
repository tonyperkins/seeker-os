"use client";

import { useState, useCallback, useEffect } from "react";
import { FileText, SlidersHorizontal, Activity } from "lucide-react";
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
import { type ProfileData, type FiltersData, type ResumeParseResult, type LangfuseStatusResponse, type SLOStatusResponse, type BudgetStatusResponse, api } from "@/lib/api";
import { Badge } from "@/components/ui/badge";
import { Progress } from "@/components/ui/progress";

export function SettingsClient({
  profile: initialProfile,
  filters: initialFilters,
}: {
  profile: ProfileData | null;
  filters: FiltersData | null;
}) {
  const [parseResult, setParseResult] = useState<ResumeParseResult | null>(null);
  const [langfuseStatus, setLangfuseStatus] = useState<LangfuseStatusResponse | null>(null);
  const [sloStatus, setSloStatus] = useState<SLOStatusResponse | null>(null);
  const [budgetStatus, setBudgetStatus] = useState<BudgetStatusResponse | null>(null);

  const handleParsed = useCallback((result: ResumeParseResult) => {
    setParseResult(result);
  }, []);

  useEffect(() => {
    api.analytics.langfuseStatus().then(setLangfuseStatus).catch(() => {});
    api.analytics.sloStatus().then(setSloStatus).catch(() => {});
    api.analytics.budgetStatus().then(setBudgetStatus).catch(() => {});
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
          <MasterResumeUpload onParsed={handleParsed} bare />
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
          <MasterResumeUpload onParsed={handleParsed} bare />
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
          />
      </CollapsibleCard>

      {/* Langfuse Observability Status */}
      {langfuseStatus && (
        <CollapsibleCard
          icon={Activity}
          title="LLM Observability"
          description="Langfuse tracing status. Configure in config/observability.yml."
        >
          <div className="flex flex-wrap items-center gap-3">
            <Badge variant={langfuseStatus.initialized ? (langfuseStatus.connection_ok ? "default" : "destructive") : langfuseStatus.enabled ? "destructive" : "secondary"}>
              {langfuseStatus.initialized
                ? (langfuseStatus.connection_ok ? "Connected" : "Connection failed")
                : langfuseStatus.enabled
                  ? "Config error"
                  : "Disabled"}
            </Badge>
            {langfuseStatus.base_url && (
              <span className="text-xs text-muted-foreground">
                URL: {langfuseStatus.base_url}
              </span>
            )}
            {langfuseStatus.enabled && (
              <span className="text-xs text-muted-foreground">
                Content capture: {langfuseStatus.capture_content ? "on" : "off"}
              </span>
            )}
            {langfuseStatus.enabled && !langfuseStatus.keys_configured && (
              <span className="text-xs text-destructive">
                Keys not configured — set LANGFUSE_PUBLIC_KEY and LANGFUSE_SECRET_KEY in .env
              </span>
            )}
            {langfuseStatus.initialized && !langfuseStatus.connection_ok && (
              <span className="text-xs text-destructive">
                Server unreachable or keys invalid — check base_url and API keys
              </span>
            )}
          </div>
        </CollapsibleCard>
      )}

      {/* SLO Status */}
      {sloStatus && (
        <CollapsibleCard
          icon={Activity}
          title="SLO Status"
          description={`Pipeline health targets over the last ${sloStatus.window_hours}h window.`}
        >
          <div className="space-y-4">
            {sloStatus.metrics.map((m) => (
              <div key={m.name} className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">{m.name.replace(/_/g, " ")}</span>
                  <Badge variant={m.passing ? "default" : "destructive"}>
                    {m.passing ? "Passing" : "Breached"}
                  </Badge>
                </div>
                <div className="flex items-center gap-2 text-xs text-muted-foreground">
                  <span>Actual: {m.actual.toLocaleString()}{m.unit}</span>
                  <span>·</span>
                  <span>Target: {m.target.toLocaleString()}{m.unit}</span>
                </div>
              </div>
            ))}
            <div className="space-y-1 border-t pt-3">
              <div className="flex items-center justify-between text-sm">
                <span className="font-medium">Daily Spend</span>
                <span className={sloStatus.daily_spend_usd > sloStatus.daily_spend_budget_usd ? "text-destructive" : "text-muted-foreground"}>
                  ${sloStatus.daily_spend_usd.toFixed(2)} / ${sloStatus.daily_spend_budget_usd.toFixed(2)}
                </span>
              </div>
              <Progress
                value={Math.min((sloStatus.daily_spend_usd / sloStatus.daily_spend_budget_usd) * 100, 100)}
                className="h-2"
              />
            </div>
          </div>
        </CollapsibleCard>
      )}

      {/* Budget Status */}
      {budgetStatus && (budgetStatus.daily_cap > 0 || budgetStatus.monthly_cap > 0) && (
        <CollapsibleCard
          icon={Activity}
          title="Retrieval Budget"
          description="Tavily API call usage against daily/monthly caps."
        >
          <div className="space-y-4">
            {budgetStatus.daily_cap > 0 && (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">Today</span>
                  <span className="text-muted-foreground">
                    {budgetStatus.daily_count} / {budgetStatus.daily_cap} calls
                    {budgetStatus.daily_errors > 0 && (
                      <span className="text-destructive"> ({budgetStatus.daily_errors} errors)</span>
                    )}
                  </span>
                </div>
                <Progress
                  value={Math.min((budgetStatus.daily_count / budgetStatus.daily_cap) * 100, 100)}
                  className="h-2"
                />
              </div>
            )}
            {budgetStatus.monthly_cap > 0 && (
              <div className="space-y-1">
                <div className="flex items-center justify-between text-sm">
                  <span className="font-medium">This Month</span>
                  <span className="text-muted-foreground">
                    {budgetStatus.monthly_count} / {budgetStatus.monthly_cap} calls
                  </span>
                </div>
                <Progress
                  value={Math.min((budgetStatus.monthly_count / budgetStatus.monthly_cap) * 100, 100)}
                  className="h-2"
                />
              </div>
            )}
          </div>
        </CollapsibleCard>
      )}
    </div>
  );
}
