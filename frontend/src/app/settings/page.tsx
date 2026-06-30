import {
  CheckCircle2,
  XCircle,
  FileText,
  SlidersHorizontal,
  ListChecks,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
  CardAction,
} from "@/components/ui/card";
import { Separator } from "@/components/ui/separator";
import { SettingsClient } from "@/components/settings-client";
import { SettingsConfigCard } from "@/components/settings-config-card";
import { AccuracyRulesCard } from "@/components/accuracy-rules-card";
import { CompanyResearchSettingsCard } from "@/components/company-research-settings-card";
import { BackupRestoreCard } from "@/components/backup-restore-card";
import { BookmarkletCard } from "@/components/bookmarklet-card";
import { api, type SettingsResponse, type ProfileData, type FiltersData, type AccuracyRule } from "@/lib/api";

export const dynamic = "force-dynamic";

export default async function SettingsPage() {
  let settings: SettingsResponse | null = null;
  let profile: ProfileData | null = null;
  let filters: FiltersData | null = null;
  let accuracyRules: AccuracyRule[] = [];
  let error: string | null = null;

  try {
    const [s, p, f, ar] = await Promise.all([
      api.settings.get(),
      api.profile.get().catch(() => null),
      api.filters.get().catch(() => null),
      api.accuracyRules.get().catch(() => null),
    ]);
    settings = s;
    profile = p;
    filters = f;
    accuracyRules = ar?.rules ?? [];
  } catch (err) {
    error = err instanceof Error ? err.message : "Failed to load settings";
  }

  if (error) {
    return (
      <div className="flex flex-col gap-4">
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
        <Card>
          <CardContent className="py-10 text-center text-destructive">
            {error}
          </CardContent>
        </Card>
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-bold tracking-tight">Settings</h1>
      </div>

      {/* Status summary */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Card size="sm">
          <CardHeader>
            <CardDescription>Profile loaded</CardDescription>
            <CardTitle className="text-lg">
              {settings?.profile_loaded ? "Yes" : "No"}
            </CardTitle>
            <CardAction>
              {settings?.profile_loaded ? (
                <CheckCircle2 className="size-5 text-emerald-500" />
              ) : (
                <XCircle className="size-5 text-destructive" />
              )}
            </CardAction>
          </CardHeader>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardDescription>Queries count</CardDescription>
            <CardTitle className="text-lg">{settings?.queries_count ?? 0}</CardTitle>
            <CardAction>
              <ListChecks className="size-5 text-muted-foreground" />
            </CardAction>
          </CardHeader>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardDescription>Filters config</CardDescription>
            <CardTitle className="text-lg">
              {settings?.filters ? "Loaded" : "Empty"}
            </CardTitle>
            <CardAction>
              <SlidersHorizontal className="size-5 text-muted-foreground" />
            </CardAction>
          </CardHeader>
        </Card>
        <Card size="sm">
          <CardHeader>
            <CardDescription>Scoring config</CardDescription>
            <CardTitle className="text-lg">
              {settings?.scoring ? "Loaded" : "Empty"}
            </CardTitle>
            <CardAction>
              <FileText className="size-5 text-muted-foreground" />
            </CardAction>
          </CardHeader>
        </Card>
      </div>

      {/* Resume Upload + Parse — the main CTA */}
      <SettingsClient
        profile={profile}
        filters={filters}
      />

      <Separator />

      {/* Bookmarklet — drag-to-bookmarks-bar job adder */}
      <BookmarkletCard />

      <Separator />

      {/* Accuracy Rules — editable resume validation constraints */}
      <AccuracyRulesCard initialRules={accuracyRules} />

      <Separator />

      {/* Company Research — retrieval provider and API key configuration */}
      <CompanyResearchSettingsCard />

      <Separator />

      {/* Advanced config — Scoring/Sources toggle lives inside the card */}
      <SettingsConfigCard
        scoring={settings?.scoring ?? null}
        sources={settings?.sources ?? null}
      />

      <Separator />

      {/* Backup & Restore — export/import all non-DB configuration */}
      <BackupRestoreCard />
    </div>
  );
}
