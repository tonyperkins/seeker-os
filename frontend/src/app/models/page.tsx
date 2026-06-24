"use client";

import { useEffect, useState, useCallback } from "react";
import {
  Loader2,
  AlertCircle,
  RefreshCw,
  Activity,
  Layers,
  ListChecks,
  Cpu,
  Zap,
} from "lucide-react";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import { EditProviderDialog } from "@/components/edit-provider-dialog";
import {
  api,
  type ProvidersConfigResponse,
  type ProviderInfoResponse,
  type ModelInfoResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";

interface HealthResult {
  provider_id: string;
  healthy: boolean;
  message: string;
  latency_ms: number;
}

const TIER_BADGE_CLASS: Record<string, string> = {
  heavy: "bg-blue-500/15 text-blue-700 dark:text-blue-300 border-blue-500/30",
  moderate: "bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/30",
  light: "bg-yellow-500/15 text-yellow-700 dark:text-yellow-300 border-yellow-500/30",
};

function tierBadgeClass(tag: string): string {
  return (
    TIER_BADGE_CLASS[tag] ||
    "bg-muted text-muted-foreground border-border"
  );
}

function HealthBadge({ provider }: { provider: ProviderInfoResponse }) {
  if (provider.healthy === true) {
    return (
      <Badge className="bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/30">
        Healthy
      </Badge>
    );
  }
  if (provider.healthy === false) {
    return (
      <Badge className="bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30">
        Unhealthy
      </Badge>
    );
  }
  return (
    <Badge variant="secondary" className="bg-muted text-muted-foreground">
      Unknown
    </Badge>
  );
}

function ProviderCard({
  provider,
  onTest,
  onFetch,
  onSaved,
  testing,
  fetching,
  testResult,
}: {
  provider: ProviderInfoResponse;
  onTest: () => void;
  onFetch: () => void;
  onSaved: () => void;
  testing: boolean;
  fetching: boolean;
  testResult: HealthResult | null;
}) {
  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <div className="space-y-1">
            <CardTitle className="flex items-center gap-2 text-base">
              <Cpu className="h-4 w-4 text-muted-foreground" />
              {provider.label}
            </CardTitle>
            <CardDescription className="font-mono text-xs">
              {provider.id} · {provider.type}
            </CardDescription>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <HealthBadge provider={provider} />
            <Badge
              variant={provider.enabled ? "default" : "secondary"}
              className={cn(
                !provider.enabled && "bg-muted text-muted-foreground"
              )}
            >
              {provider.enabled ? "Enabled" : "Disabled"}
            </Badge>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 pt-1">
          <Button size="sm" variant="outline" onClick={onTest} disabled={testing}>
            {testing ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Activity className="h-3.5 w-3.5" />
            )}
            Test Connection
          </Button>
          {provider.auto_fetch_models && (
            <Button size="sm" variant="outline" onClick={onFetch} disabled={fetching}>
              {fetching ? (
                <Loader2 className="h-3.5 w-3.5 animate-spin" />
              ) : (
                <RefreshCw className="h-3.5 w-3.5" />
              )}
              Fetch Models
            </Button>
          )}
          <EditProviderDialog provider={provider} onSaved={onSaved} />
        </div>
        {testResult && (
          <div
            className={cn(
              "mt-1 rounded-md border px-3 py-2 text-xs",
              testResult.healthy
                ? "border-green-500/30 bg-green-500/10 text-green-700 dark:text-green-300"
                : "border-red-500/30 bg-red-500/10 text-red-700 dark:text-red-300"
            )}
          >
            <span className="font-medium">
              {testResult.healthy ? "Healthy" : "Unhealthy"}
            </span>
            {" · "}
            {testResult.latency_ms}ms — {testResult.message}
          </div>
        )}
        {provider.health_message && !testResult && (
          <p className="text-xs text-muted-foreground pt-1">
            {provider.health_message}
          </p>
        )}
      </CardHeader>
      <CardContent>
        {provider.models.length === 0 ? (
          <p className="text-sm text-muted-foreground py-4 text-center">
            No models configured.
          </p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>ID</TableHead>
                <TableHead>Label</TableHead>
                <TableHead>Tags</TableHead>
                <TableHead>Source</TableHead>
                <TableHead className="text-right">Available</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {provider.models.map((m: ModelInfoResponse) => (
                <TableRow key={m.id}>
                  <TableCell className="font-mono text-xs">{m.id}</TableCell>
                  <TableCell className="text-sm">{m.label}</TableCell>
                  <TableCell>
                    <div className="flex flex-wrap gap-1">
                      {m.tags.length === 0 ? (
                        <Badge variant="secondary" className="bg-muted text-muted-foreground">
                          untagged
                        </Badge>
                      ) : (
                        m.tags.map((t) => (
                          <Badge
                            key={t}
                            variant="outline"
                            className={cn("border", tierBadgeClass(t))}
                          >
                            {t}
                          </Badge>
                        ))
                      )}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge
                      variant="outline"
                      className={cn(
                        m.source === "auto"
                          ? "bg-blue-500/10 text-blue-700 dark:text-blue-300 border-blue-500/30"
                          : "bg-muted text-muted-foreground border-border"
                      )}
                    >
                      {m.source}
                    </Badge>
                  </TableCell>
                  <TableCell className="text-right">
                    {m.available ? (
                      <span className="text-green-600 dark:text-green-400 text-sm">●</span>
                    ) : (
                      <span className="text-muted-foreground text-sm">○</span>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}

export default function ModelsPage() {
  const [config, setConfig] = useState<ProvidersConfigResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [testingProvider, setTestingProvider] = useState<string | null>(null);
  const [fetchingProvider, setFetchingProvider] = useState<string | null>(null);
  const [testResults, setTestResults] = useState<Record<string, HealthResult>>({});
  const [testingAll, setTestingAll] = useState(false);
  const [allResults, setAllResults] = useState<HealthResult[] | null>(null);

  const loadConfig = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const data = await api.models.getConfig();
      setConfig(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load models config");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleTest = async (providerId: string) => {
    setTestingProvider(providerId);
    try {
      const res = (await api.models.test(providerId)) as unknown as HealthResult;
      setTestResults((prev) => ({ ...prev, [providerId]: res }));
      // Refresh config to pick up updated health status
      await loadConfig();
    } catch (e) {
      setTestResults((prev) => ({
        ...prev,
        [providerId]: {
          provider_id: providerId,
          healthy: false,
          message: e instanceof Error ? e.message : "Test failed",
          latency_ms: 0,
        },
      }));
    } finally {
      setTestingProvider(null);
    }
  };

  const handleFetch = async (providerId: string) => {
    setFetchingProvider(providerId);
    try {
      await api.models.fetch(providerId);
      await loadConfig();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch models");
    } finally {
      setFetchingProvider(null);
    }
  };

  const handleTestAll = async () => {
    setTestingAll(true);
    setAllResults(null);
    try {
      const res = (await api.models.testAll()) as unknown as HealthResult[];
      setAllResults(res);
      const map: Record<string, HealthResult> = {};
      for (const r of res) map[r.provider_id] = r;
      setTestResults((prev) => ({ ...prev, ...map }));
      await loadConfig();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to test all providers");
    } finally {
      setTestingAll(false);
    }
  };

  if (loading) {
    return (
      <div className="flex items-center justify-center py-20">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
      </div>
    );
  }

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center py-20 gap-3">
        <AlertCircle className="h-8 w-8 text-red-500" />
        <p className="text-sm text-red-600 dark:text-red-400">{error}</p>
        <Button variant="outline" size="sm" onClick={loadConfig}>
          <RefreshCw className="h-3.5 w-3.5" />
          Retry
        </Button>
      </div>
    );
  }

  if (!config) return null;

  const tierOrder = ["heavy", "moderate", "light"];
  const tiers = tierOrder
    .filter((t) => config.tiers[t])
    .map((t) => ({ tier: t, ...config.tiers[t] }));
  const taskEntries = Object.entries(config.tasks);

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <div>
          <h1 className="text-2xl font-bold tracking-tight">Models &amp; Providers</h1>
          <p className="text-sm text-muted-foreground mt-1">
            Manage LLM providers, model discovery, and tier routing.
          </p>
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={loadConfig}>
            <RefreshCw className="h-3.5 w-3.5" />
            Refresh
          </Button>
          <Button size="sm" onClick={handleTestAll} disabled={testingAll}>
            {testingAll ? (
              <Loader2 className="h-3.5 w-3.5 animate-spin" />
            ) : (
              <Zap className="h-3.5 w-3.5" />
            )}
            Test All
          </Button>
        </div>
      </div>

      {allResults && (
        <Card>
          <CardHeader className="pb-3">
            <CardTitle className="text-sm flex items-center gap-2">
              <Activity className="h-4 w-4" />
              Test All Results
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
              {allResults.map((r) => (
                <div
                  key={r.provider_id}
                  className={cn(
                    "rounded-md border px-3 py-2 text-xs",
                    r.healthy
                      ? "border-green-500/30 bg-green-500/10"
                      : "border-red-500/30 bg-red-500/10"
                  )}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-mono font-medium">{r.provider_id}</span>
                    <Badge
                      className={cn(
                        r.healthy
                          ? "bg-green-500/15 text-green-700 dark:text-green-300 border-green-500/30"
                          : "bg-red-500/15 text-red-700 dark:text-red-300 border-red-500/30"
                      )}
                    >
                      {r.healthy ? "Healthy" : "Unhealthy"}
                    </Badge>
                  </div>
                  <p className="text-muted-foreground mt-1">
                    {r.latency_ms}ms — {r.message}
                  </p>
                </div>
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <div>
        <h2 className="text-lg font-semibold mb-3 flex items-center gap-2">
          <Cpu className="h-5 w-5 text-muted-foreground" />
          Providers
        </h2>
        {config.providers.length === 0 ? (
          <Card>
            <CardContent className="py-10 text-center text-sm text-muted-foreground">
              No providers configured. Add providers in <code className="font-mono">providers.yml</code>.
            </CardContent>
          </Card>
        ) : (
          <div className="grid gap-4 lg:grid-cols-2">
            {config.providers.map((p) => (
              <ProviderCard
                key={p.id}
                provider={p}
                testing={testingProvider === p.id}
                fetching={fetchingProvider === p.id}
                testResult={testResults[p.id] ?? null}
                onTest={() => handleTest(p.id)}
                onFetch={() => handleFetch(p.id)}
                onSaved={loadConfig}
              />
            ))}
          </div>
        )}
      </div>

      <Separator />

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <Layers className="h-4 w-4 text-muted-foreground" />
              Tier Mappings
            </CardTitle>
            <CardDescription>
              Default provider + model for each routing tier.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {tiers.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No tier mappings configured.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Tier</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Model</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {tiers.map((t) => (
                    <TableRow key={t.tier}>
                      <TableCell>
                        <Badge variant="outline" className={cn("border", tierBadgeClass(t.tier))}>
                          {t.tier}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">{t.provider}</TableCell>
                      <TableCell className="font-mono text-xs">{t.model}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle className="text-base flex items-center gap-2">
              <ListChecks className="h-4 w-4 text-muted-foreground" />
              Task Overrides
            </CardTitle>
            <CardDescription>
              Per-task model selection overrides.
            </CardDescription>
          </CardHeader>
          <CardContent>
            {taskEntries.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No task overrides configured.
              </p>
            ) : (
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead>Task</TableHead>
                    <TableHead>Tier</TableHead>
                    <TableHead>Provider</TableHead>
                    <TableHead>Model</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {taskEntries.map(([task, ov]) => (
                    <TableRow key={task}>
                      <TableCell className="font-mono text-xs">{task}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className={cn("border", tierBadgeClass(ov.tier))}>
                          {ov.tier}
                        </Badge>
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {ov.provider ?? <span className="text-muted-foreground">—</span>}
                      </TableCell>
                      <TableCell className="font-mono text-xs">
                        {ov.model ?? <span className="text-muted-foreground">—</span>}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
