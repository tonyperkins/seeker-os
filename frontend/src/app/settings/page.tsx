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
import { SettingsTabs } from "@/components/settings-tabs";
import { PageHeader } from "@/components/page-header";
import { ReloadConfigButton } from "@/components/reload-config-button";
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
        <PageHeader title="Settings" />
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
      <PageHeader title="Settings" actions={<ReloadConfigButton />} />

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

      <SettingsTabs
        profile={profile}
        filters={filters}
        accuracyRules={accuracyRules}
        scoring={settings?.scoring ?? null}
        sources={settings?.sources ?? null}
      />
    </div>
  );
}
