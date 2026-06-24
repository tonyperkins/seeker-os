import {
  CheckCircle2,
  XCircle,
  FileText,
  SlidersHorizontal,
  Server,
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
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import { Separator } from "@/components/ui/separator";
import { MasterResumeUpload } from "@/components/master-resume-upload";
import { api, type SettingsResponse } from "@/lib/api";

function ConfigViewer({ data }: { data: Record<string, unknown> | null }) {
  if (!data) {
    return (
      <p className="py-6 text-center text-sm text-muted-foreground">
        No configuration loaded.
      </p>
    );
  }
  return (
    <pre className="overflow-x-auto rounded-md bg-muted/50 p-4 text-xs leading-relaxed font-mono">
      {JSON.stringify(data, null, 2)}
    </pre>
  );
}

export default async function SettingsPage() {
  let settings: SettingsResponse | null = null;
  let error: string | null = null;

  try {
    settings = await api.settings.get();
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
        <p className="text-sm text-muted-foreground">
          Configuration loaded from YAML files. Read-only for now — editing comes later.
        </p>
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

      {/* Tabs */}
      <Tabs defaultValue="filters">
        <TabsList>
          <TabsTrigger value="filters">
            <SlidersHorizontal className="size-4" />
            Filters
          </TabsTrigger>
          <TabsTrigger value="scoring">
            <FileText className="size-4" />
            Scoring
          </TabsTrigger>
          <TabsTrigger value="sources">
            <Server className="size-4" />
            Sources
          </TabsTrigger>
        </TabsList>

        <TabsContent value="filters">
          <Card>
            <CardHeader>
              <CardTitle>Filters Configuration</CardTitle>
              <CardDescription>
                Tier-2 hard filters applied before JD fetch. From{" "}
                <code className="text-xs">config/filters.yml</code>.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ConfigViewer data={settings?.filters ?? null} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="scoring">
          <Card>
            <CardHeader>
              <CardTitle>Scoring Configuration</CardTitle>
              <CardDescription>
                Scoring rubric weights, patterns, and thresholds. From{" "}
                <code className="text-xs">config/scoring_rubric.yml</code>.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ConfigViewer data={settings?.scoring ?? null} />
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sources">
          <Card>
            <CardHeader>
              <CardTitle>Sources Configuration</CardTitle>
              <CardDescription>
                Source adapters and ATS source mapping. From{" "}
                <code className="text-xs">config/sources.yml</code>.
              </CardDescription>
            </CardHeader>
            <CardContent>
              <ConfigViewer data={settings?.sources ?? null} />
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>

      <Separator />

      {/* Master Resume */}
      <MasterResumeUpload />

      <Separator />

      <p className="text-xs text-muted-foreground">
        Configuration is the source of truth. YAML files win on startup; the database
        is a derived cache. Editing in the UI will be available in a future phase.
      </p>
    </div>
  );
}
