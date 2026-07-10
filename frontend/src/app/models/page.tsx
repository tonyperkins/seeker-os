"use client";

import { useEffect, useState, useCallback, useMemo, useRef } from "react";
import {
  Loader2,
  AlertCircle,
  RefreshCw,
  Activity,
  Layers,
  ListChecks,
  Cpu,
  Zap,
  Search,
  ChevronDown,
  DollarSign,
  RotateCcw,
  Check,
  X,
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
import { Input } from "@/components/ui/input";
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table";
import { Separator } from "@/components/ui/separator";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { EditProviderDialog } from "@/components/edit-provider-dialog";
import {
  api,
  type ProvidersConfigResponse,
  type ProviderInfoResponse,
  type ModelInfoResponse,
} from "@/lib/api";
import { cn } from "@/lib/utils";
import { usePersistentState } from "@/lib/use-persistent-state";

interface HealthResult {
  provider_id: string;
  healthy: boolean;
  message: string;
  latency_ms: number;
}

const providerTypeLabel: Record<string, string> = {
  anthropic: "Anthropic",
  openai_compatible: "OpenAI-compatible",
};

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
  return null;
}

function PricingRow({
  providerId,
  model,
  onSaved,
}: {
  providerId: string;
  model: ModelInfoResponse;
  onSaved: () => void | Promise<void>;
}) {
  const [inputPrice, setInputPrice] = useState(
    model.input_price_per_mtok != null ? String(model.input_price_per_mtok) : "",
  );
  const [outputPrice, setOutputPrice] = useState(
    model.output_price_per_mtok != null ? String(model.output_price_per_mtok) : "",
  );
  const [saving, setSaving] = useState(false);
  const [resetting, setResetting] = useState(false);

  // Sync from server data when it changes (e.g. after fetch/reset)
  useEffect(() => {
    setInputPrice(model.input_price_per_mtok != null ? String(model.input_price_per_mtok) : "");
    setOutputPrice(model.output_price_per_mtok != null ? String(model.output_price_per_mtok) : "");
  }, [model.input_price_per_mtok, model.output_price_per_mtok]);

  const dirty =
    inputPrice !== (model.input_price_per_mtok != null ? String(model.input_price_per_mtok) : "") ||
    outputPrice !== (model.output_price_per_mtok != null ? String(model.output_price_per_mtok) : "");

  async function handleSave() {
    setSaving(true);
    try {
      const inVal = inputPrice.trim() === "" ? null : parseFloat(inputPrice);
      const outVal = outputPrice.trim() === "" ? null : parseFloat(outputPrice);
      await api.models.updateModelPricing(providerId, model.id, inVal, outVal);
      await onSaved();
    } catch {
      // error handled by parent
    } finally {
      setSaving(false);
    }
  }

  async function handleReset() {
    setResetting(true);
    try {
      await api.models.resetModelPricing(providerId, model.id);
      await onSaved();
    } catch {
      // error handled by parent
    } finally {
      setResetting(false);
    }
  }

  const canReset = model.pricing_source === "manual";

  return (
    <div className="flex items-center gap-1">
      <Input
        type="number"
        step="0.01"
        min="0"
        placeholder="—"
        value={inputPrice}
        onChange={(e) => setInputPrice(e.target.value)}
        className="h-7 w-20 px-1.5 text-xs font-mono"
      />
      <Input
        type="number"
        step="0.01"
        min="0"
        placeholder="—"
        value={outputPrice}
        onChange={(e) => setOutputPrice(e.target.value)}
        className="h-7 w-20 px-1.5 text-xs font-mono"
      />
      <div className="flex items-center gap-0.5 shrink-0">
        {model.pricing_source === "auto" && (
          <span className="text-[10px] text-blue-500" title="Auto-fetched from provider API">auto</span>
        )}
        {model.pricing_source === "manual" && (
          <span className="text-[10px] text-amber-500" title="Manually entered">manual</span>
        )}
        {dirty && (
          <>
            <button
              onClick={() => {
                setInputPrice(model.input_price_per_mtok != null ? String(model.input_price_per_mtok) : "");
                setOutputPrice(model.output_price_per_mtok != null ? String(model.output_price_per_mtok) : "");
              }}
              disabled={saving}
              className="rounded p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-50"
              title="Cancel"
            >
              <X className="size-3" />
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              className="rounded p-0.5 text-emerald-600 hover:bg-emerald-500/10 disabled:opacity-50"
              title="Save pricing"
            >
              {saving ? <Loader2 className="size-3 animate-spin" /> : <Check className="size-3" />}
            </button>
          </>
        )}
        {canReset && !dirty && (
          <button
            onClick={handleReset}
            disabled={resetting}
            className="rounded p-0.5 text-muted-foreground hover:text-foreground disabled:opacity-50"
            title="Reset to auto-fetched pricing"
          >
            {resetting ? <Loader2 className="size-3 animate-spin" /> : <RotateCcw className="size-3" />}
          </button>
        )}
      </div>
    </div>
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
  onSaved: () => void | Promise<void>;
  testing: boolean;
  fetching: boolean;
  testResult: HealthResult | null;
}) {
  const [search, setSearch] = useState("");
  const [expanded, setExpanded] = usePersistentState(`models:provider:${provider.id}:expanded`, true);

  const filteredModels = useMemo(() => {
    if (!search.trim()) return provider.models;
    const q = search.toLowerCase();
    return provider.models.filter(
      (m) => m.id.toLowerCase().includes(q) || m.label.toLowerCase().includes(q),
    );
  }, [provider.models, search]);

  const showSearch = provider.models.length > 12;

  return (
    <Card>
      <CardHeader className="pb-3">
        <div className="flex items-start justify-between gap-3">
          <button
            className="flex items-start gap-2 text-left flex-1 min-w-0"
            onClick={() => setExpanded((e) => !e)}
          >
            <ChevronDown
              className={cn(
                "mt-0.5 h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                !expanded && "-rotate-90",
              )}
            />
            <div className="space-y-1 min-w-0">
              <CardTitle className="flex items-center gap-2 text-base">
                <Cpu className="h-4 w-4 text-muted-foreground" />
                {provider.label}
              </CardTitle>
              <CardDescription className="font-mono text-xs">
                {provider.id} · {providerTypeLabel[provider.type] ?? provider.type}
                {provider.models.length > 0 && (
                  <span className="ml-1">
                    · {provider.models.length} model{provider.models.length !== 1 ? "s" : ""}
                  </span>
                )}
              </CardDescription>
            </div>
          </button>
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
        {expanded && (
          <>
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
            {(() => {
              const hasAuto = provider.models.some((m) => m.pricing_source === "auto");
              const hasManual = provider.models.some((m) => m.pricing_source === "manual");
              const hasNone = provider.models.some((m) => m.pricing_source == null);
              if (!hasAuto && !hasManual && !hasNone) return null;
              return (
                <p className="text-xs text-muted-foreground pt-1 flex items-center gap-1.5">
                  <DollarSign className="size-3" />
                  {hasAuto && <span>Pricing auto-fetched from provider</span>}
                  {hasAuto && hasManual && <span>·</span>}
                  {hasManual && <span>Manual overrides active</span>}
                  {hasNone && (hasAuto || hasManual) && <span>·</span>}
                  {hasNone && <span>Some models have no pricing — enter manually for cost estimates</span>}
                </p>
              );
            })()}
          </>
        )}
      </CardHeader>
      {expanded && (
        <CardContent>
          {provider.models.length === 0 ? (
            <p className="text-sm text-muted-foreground py-4 text-center">
              No models configured.
            </p>
          ) : (
            <>
              {showSearch && (
                <div className="relative mb-3">
                  <Search className="absolute left-2.5 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                  <Input
                    type="text"
                    placeholder="Search models…"
                    value={search}
                    onChange={(e) => setSearch(e.target.value)}
                    className="h-8 pl-8 text-sm"
                  />
                  {search && (
                    <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-xs text-muted-foreground">
                      {filteredModels.length}/{provider.models.length}
                    </span>
                  )}
                </div>
              )}
              <div className="max-h-80 overflow-y-auto rounded-md border border-border">
                <Table>
                  <TableHeader className="sticky top-0 z-10 bg-background">
                    <TableRow>
                      <TableHead className="min-w-[120px]">ID</TableHead>
                      <TableHead className="min-w-[100px]">Label</TableHead>
                      <TableHead className="min-w-[80px]">Tags</TableHead>
                      <TableHead className="w-20">Source</TableHead>
                      <TableHead className="min-w-[200px]">Pricing ($/Mtok)</TableHead>
                      <TableHead className="w-16 text-right">Avail</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {filteredModels.length === 0 ? (
                      <TableRow>
                        <TableCell colSpan={6} className="text-center text-sm text-muted-foreground py-6">
                          No models match &ldquo;{search}&rdquo;
                        </TableCell>
                      </TableRow>
                    ) : (
                      filteredModels.map((m: ModelInfoResponse) => (
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
                          <TableCell>
                            <PricingRow
                              providerId={provider.id}
                              model={m}
                              onSaved={onSaved}
                            />
                          </TableCell>
                          <TableCell className="text-right">
                            {m.available ? (
                              <span className="text-green-600 dark:text-green-400 text-sm">●</span>
                            ) : (
                              <span className="text-muted-foreground text-sm">○</span>
                            )}
                          </TableCell>
                        </TableRow>
                      ))
                    )}
                  </TableBody>
                </Table>
              </div>
            </>
          )}
        </CardContent>
      )}
    </Card>
  );
}

function SearchableModelSelect({
  models,
  value,
  onChange,
}: {
  models: ModelInfoResponse[];
  value: string;
  onChange: (modelId: string) => void;
}) {
  const [query, setQuery] = useState("");
  const [open, setOpen] = useState(false);
  const [highlight, setHighlight] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = useMemo(() => {
    if (!query.trim()) return models;
    const q = query.toLowerCase();
    return models.filter(
      (m) => m.id.toLowerCase().includes(q) || m.label.toLowerCase().includes(q),
    );
  }, [models, query]);

  useEffect(() => {
    setHighlight(0);
  }, [query]);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
        setQuery("");
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const selectedModel = models.find((m) => m.id === value);

  function handleSelect(modelId: string) {
    onChange(modelId);
    setOpen(false);
    setQuery("");
  }

  function handleKeyDown(e: React.KeyboardEvent) {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setHighlight((h) => Math.min(h + 1, filtered.length - 1));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setHighlight((h) => Math.max(h - 1, 0));
    } else if (e.key === "Enter") {
      e.preventDefault();
      if (filtered[highlight]) handleSelect(filtered[highlight].id);
    } else if (e.key === "Escape") {
      setOpen(false);
      setQuery("");
    }
  }

  return (
    <div ref={containerRef} className="relative">
      <div
        className="flex h-8 items-center gap-1 rounded-md border border-border bg-background px-2 text-xs font-mono cursor-pointer"
        onClick={() => {
          setOpen(true);
          setQuery("");
          inputRef.current?.focus();
        }}
      >
        <Search className="size-3 shrink-0 text-muted-foreground" />
        {open ? (
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onKeyDown={handleKeyDown}
            placeholder="Search models…"
            className="flex-1 bg-transparent outline-none text-xs font-mono text-foreground placeholder:text-muted-foreground"
          />
        ) : (
          <span className={selectedModel ? "text-foreground" : "text-muted-foreground"}>
            {selectedModel?.id || "(no model)"}
          </span>
        )}
      </div>
      {open && (
        <div className="absolute z-20 mt-1 max-h-48 w-full overflow-y-auto rounded-md border border-border bg-background shadow-md">
          {filtered.length === 0 ? (
            <div className="px-2 py-3 text-center text-xs text-muted-foreground">
              No models match &ldquo;{query}&rdquo;
            </div>
          ) : (
            filtered.map((m, i) => (
              <button
                key={m.id}
                onClick={() => handleSelect(m.id)}
                onMouseEnter={() => setHighlight(i)}
                className={cn(
                  "flex w-full items-center justify-between gap-2 px-2 py-1.5 text-left text-xs",
                  i === highlight ? "bg-accent text-accent-foreground" : "hover:bg-accent/50",
                )}
              >
                <span className="font-mono truncate">{m.id}</span>
                <span className="text-muted-foreground shrink-0">{m.label}</span>
              </button>
            ))
          )}
        </div>
      )}
    </div>
  );
}

function TierRow({
  tier,
  currentProvider,
  currentModel,
  providers,
  providerModels,
  saving,
  onSave,
}: {
  tier: string;
  currentProvider: string;
  currentModel: string;
  providers: ProviderInfoResponse[];
  providerModels: Record<string, ModelInfoResponse[]>;
  saving: boolean;
  onSave: (tier: string, provider: string, model: string) => void | Promise<void>;
}) {
  const [provider, setProvider] = useState(currentProvider);
  const [model, setModel] = useState(currentModel);

  const dirty = provider !== currentProvider || model !== currentModel;
  const models = providerModels[provider] ?? [];

  function handleProviderChange(val: string) {
    setProvider(val);
    const newModels = providerModels[val] ?? [];
    if (newModels.length > 0 && !newModels.some((m) => m.id === model)) {
      setModel(newModels[0].id);
    }
  }

  function handleCancel() {
    setProvider(currentProvider);
    setModel(currentModel);
  }

  return (
    <div className="grid grid-cols-[72px_220px_1fr_auto] items-center gap-2 rounded-md border border-border px-3 py-2">
      <Badge variant="outline" className={cn("border justify-center", tierBadgeClass(tier))}>
        {tier}
      </Badge>
      <Select
        value={provider}
        onValueChange={(v) => handleProviderChange(v ?? "")}
      >
        <SelectTrigger className="h-8 w-full border-border bg-background px-2 text-xs font-mono">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {providers.map((p) => (
            <SelectItem
              key={p.id}
              value={p.id}
              className={cn("text-xs font-mono", !p.enabled && "text-muted-foreground")}
            >
              {p.id}{!p.enabled && " (disabled)"}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <div className="min-w-0">
        <SearchableModelSelect
          models={models}
          value={model}
          onChange={setModel}
        />
      </div>
      <div className="flex items-center gap-1 justify-end">
        {dirty && (
          <>
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs text-muted-foreground hover:text-foreground"
              disabled={saving}
              onClick={handleCancel}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-6 text-xs"
              disabled={saving}
              onClick={async () => { await onSave(tier, provider, model); }}
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}

function TierTaskEditor({
  tiers,
  taskEntries,
  providers,
  onSaved,
}: {
  tiers: { tier: string; provider: string; model: string }[];
  taskEntries: [string, { tier: string; provider: string | null; model: string | null; default_tier?: string | null }][];
  providers: ProviderInfoResponse[];
  onSaved: () => void | Promise<void>;
}) {
  const [saving, setSaving] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [tiersExpanded, setTiersExpanded] = usePersistentState("models:tierMappings:expanded", true);
  const [tasksExpanded, setTasksExpanded] = usePersistentState("models:taskOverrides:expanded", true);

  // Build a map of provider → models for dropdowns
  const providerModels: Record<string, ModelInfoResponse[]> = {};
  for (const p of providers) {
    providerModels[p.id] = p.models;
  }

  async function handleTierSave(tier: string, provider: string, model: string) {
    setSaving(`tier-${tier}`);
    setError(null);
    try {
      await api.models.updateTier(tier, provider, model);
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save tier mapping");
    } finally {
      setSaving(null);
    }
  }

  async function handleTaskSave(
    task: string,
    tier: string,
    provider: string | null,
    model: string | null,
  ) {
    setSaving(`task-${task}`);
    setError(null);
    try {
      await api.models.updateTask(task, { tier, provider: provider ?? undefined, model: model ?? undefined });
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save task override");
    } finally {
      setSaving(null);
    }
  }

  const [resettingAll, setResettingAll] = useState(false);

  const nonDefaultTasks = taskEntries.filter(([task, ov]) => {
    const isCustom = ov.provider !== null || ov.model !== null;
    const defaultTier = ov.default_tier ?? "moderate";
    return isCustom || ov.tier !== defaultTier;
  });

  async function handleResetAllTasks() {
    setResettingAll(true);
    setError(null);
    try {
      await Promise.all(
        nonDefaultTasks.map(([task, ov]) => {
          const defaultTier = ov.default_tier ?? "moderate";
          return api.models.updateTask(task, { tier: defaultTier });
        }),
      );
      await onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to reset task overrides");
    } finally {
      setResettingAll(false);
    }
  }

  return (
    <div className="flex flex-col gap-6">
      <Card className="overflow-visible">
        <CardHeader>
          <button
            className="flex items-center gap-2 text-left"
            onClick={() => setTiersExpanded((e) => !e)}
          >
            <ChevronDown
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                !tiersExpanded && "-rotate-90",
              )}
            />
            <div className="space-y-1">
              <CardTitle className="text-base flex items-center gap-2">
                <Layers className="h-4 w-4 text-muted-foreground" />
                Tier Mappings
              </CardTitle>
              <CardDescription>
                Default provider + model for each routing tier. Changes save to providers.yml.
              </CardDescription>
            </div>
          </button>
        </CardHeader>
        {tiersExpanded && (
          <CardContent className="space-y-3 overflow-visible">
            {error && (
              <div className="rounded-md bg-destructive/10 p-2 text-xs text-destructive">{error}</div>
            )}
            {tiers.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No tier mappings configured.
              </p>
            ) : (
              <>
                {tiers.map((t) => (
                  <TierRow
                    key={t.tier}
                    tier={t.tier}
                    currentProvider={t.provider}
                    currentModel={t.model}
                    providers={providers}
                    providerModels={providerModels}
                    saving={saving === `tier-${t.tier}`}
                    onSave={handleTierSave}
                  />
                ))}
              </>
            )}
          </CardContent>
        )}
      </Card>

      <Card className="overflow-visible">
        <CardHeader>
          <button
            className="flex items-center gap-2 text-left"
            onClick={() => setTasksExpanded((e) => !e)}
          >
            <ChevronDown
              className={cn(
                "h-4 w-4 shrink-0 text-muted-foreground transition-transform",
                !tasksExpanded && "-rotate-90",
              )}
            />
            <div className="space-y-1">
              <CardTitle className="text-base flex items-center gap-2">
                <ListChecks className="h-4 w-4 text-muted-foreground" />
                Task Overrides
              </CardTitle>
              <CardDescription>
                Per-task model selection overrides. Changes save to providers.yml.
              </CardDescription>
            </div>
          </button>
          {nonDefaultTasks.length > 0 && (
            <Button
              size="sm"
              variant="outline"
              className="ml-auto shrink-0"
              disabled={resettingAll}
              onClick={handleResetAllTasks}
            >
              {resettingAll ? <Loader2 className="h-3.5 w-3.5 animate-spin" /> : <RotateCcw className="h-3.5 w-3.5" />}
              Reset All
            </Button>
          )}
        </CardHeader>
        {tasksExpanded && (
          <CardContent className="space-y-3 overflow-visible">
            {taskEntries.length === 0 ? (
              <p className="text-sm text-muted-foreground text-center py-4">
                No task overrides configured.
              </p>
            ) : (
              <div className="flex flex-col gap-1.5">
                {taskEntries.map(([task, ov]) => (
                  <TaskRow
                    key={`${task}-${ov.tier}-${ov.provider ?? ""}-${ov.model ?? ""}`}
                    task={task}
                    currentTier={ov.tier}
                    currentProvider={ov.provider}
                    currentModel={ov.model}
                    defaultTier={ov.default_tier ?? "moderate"}
                    providers={providers}
                    providerModels={providerModels}
                    tiers={tiers}
                    saving={saving === `task-${task}`}
                    onSave={handleTaskSave}
                  />
                ))}
              </div>
            )}
          </CardContent>
        )}
      </Card>
    </div>
  );
}

const CUSTOM_VALUE = "__custom__";

function humanizeTaskName(task: string): string {
  return task
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

function TaskRow({
  task,
  currentTier,
  currentProvider,
  currentModel,
  defaultTier,
  providers,
  providerModels,
  tiers,
  saving,
  onSave,
}: {
  task: string;
  currentTier: string;
  currentProvider: string | null;
  currentModel: string | null;
  defaultTier: string;
  providers: ProviderInfoResponse[];
  providerModels: Record<string, ModelInfoResponse[]>;
  tiers: { tier: string; provider: string; model: string }[];
  saving: boolean;
  onSave: (_task: string, _tier: string, _provider: string | null, _model: string | null) => void | Promise<void>;
}) {
  const isCustomSaved = currentProvider !== null || currentModel !== null;
  const isNonDefault = isCustomSaved || currentTier !== defaultTier;
  const [selection, setSelection] = useState(isCustomSaved ? CUSTOM_VALUE : currentTier);
  const [provider, setProvider] = useState(currentProvider ?? providers[0]?.id ?? "");
  const [model, setModel] = useState(currentModel ?? "");

  const isCustom = selection === CUSTOM_VALUE;
  const effectiveTier = isCustom ? currentTier : selection;
  const tierDefault = tiers.find((t) => t.tier === effectiveTier);
  const models = providerModels[provider] ?? [];

  const dirty = isCustom
    ? !isCustomSaved || provider !== currentProvider || model !== currentModel
    : selection !== currentTier || isCustomSaved;

  function handleSelectionChange(val: string) {
    setSelection(val);
    if (val !== CUSTOM_VALUE && provider === "") {
      setProvider(providers[0]?.id ?? "");
    }
  }

  function handleProviderChange(val: string) {
    setProvider(val);
    const newModels = providerModels[val] ?? [];
    if (newModels.length > 0 && !newModels.some((m) => m.id === model)) {
      setModel(newModels[0].id);
    }
  }

  async function handleSave() {
    const saveTier = isCustom ? effectiveTier : selection;
    await onSave(task, saveTier, isCustom ? provider : null, isCustom ? model : null);
  }

  function handleReset() {
    setSelection(defaultTier);
    onSave(task, defaultTier, null, null);
  }

  function handleCancel() {
    setSelection(isCustomSaved ? CUSTOM_VALUE : currentTier);
    setProvider(currentProvider ?? providers[0]?.id ?? "");
    setModel(currentModel ?? "");
  }

  return (
    <div className={cn(
      "grid grid-cols-[minmax(180px,220px)_auto_1fr_auto] items-center gap-x-3 rounded-md border px-3 py-2",
      isNonDefault ? "border-amber-500/40" : "border-border",
    )}>
      {/* Task name + indicator */}
      <div className="flex items-center gap-1.5 min-w-0">
        <span className="text-sm font-medium truncate" title={task}>{humanizeTaskName(task)}</span>
        {isNonDefault && (
          <span className="shrink-0 text-[10px] font-medium text-amber-600 dark:text-amber-400" title={`Default: ${defaultTier}`}>
            non-default
          </span>
        )}
      </div>

      {/* Unified tier/custom dropdown */}
      <select
        value={selection}
        onChange={(e) => handleSelectionChange(e.target.value)}
        className={cn(
          "h-7 rounded-md border bg-background px-1.5 text-xs font-mono text-foreground",
          isCustom ? "border-primary/60" : "border-border",
        )}
      >
        <option value="heavy" className="bg-background text-foreground">Heavy</option>
        <option value="moderate" className="bg-background text-foreground">Moderate</option>
        <option value="light" className="bg-background text-foreground">Light</option>
        <option value={CUSTOM_VALUE} className="bg-background text-foreground">Custom model...</option>
      </select>

      {/* Right side: default hint OR custom provider+model pickers */}
      <div className="flex items-center gap-2 min-w-0">
        {isCustom ? (
          <>
            <select
              value={provider}
              onChange={(e) => handleProviderChange(e.target.value)}
              className="h-7 min-w-[100px] rounded-md border border-border bg-background px-1.5 text-xs font-mono text-foreground shrink-0"
            >
              {providers.map((p) => (
                <option
                  key={p.id}
                  value={p.id}
                  className={cn("bg-background text-foreground", !p.enabled && "text-muted-foreground")}
                >
                  {p.id}{!p.enabled && " (disabled)"}
                </option>
              ))}
            </select>
            <div className="min-w-[140px] flex-1">
              <SearchableModelSelect models={models} value={model} onChange={setModel} />
            </div>
          </>
        ) : (
          <span className="text-xs text-muted-foreground" title={`Default for ${selection} tier`}>
            {tierDefault ? (
              <>
                <span className="font-mono">{tierDefault.provider}</span>
                <span className="mx-1 opacity-40">/</span>
                <span className="font-mono">{tierDefault.model}</span>
              </>
            ) : (
              <span className="italic">no default configured</span>
            )}
          </span>
        )}
      </div>

      {/* Actions */}
      <div className="flex items-center gap-2 justify-end">
        {isNonDefault && !dirty && (
          <Button
            size="sm"
            variant="ghost"
            className="h-6 text-xs text-muted-foreground hover:text-foreground"
            disabled={saving}
            onClick={handleReset}
          >
            Reset to default
          </Button>
        )}
        {dirty && (
          <div className="flex items-center gap-1">
            <Button
              size="sm"
              variant="ghost"
              className="h-6 text-xs text-muted-foreground hover:text-foreground"
              disabled={saving}
              onClick={handleCancel}
            >
              Cancel
            </Button>
            <Button
              size="sm"
              className="h-6 text-xs"
              disabled={saving}
              onClick={handleSave}
            >
              {saving ? <Loader2 className="h-3 w-3 animate-spin" /> : "Save"}
            </Button>
          </div>
        )}
      </div>
    </div>
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

  const loadConfig = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const data = await api.models.getConfig();
      setConfig(data);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load models config");
    } finally {
      if (!silent) setLoading(false);
    }
  }, []);

  const reloadConfig = useCallback(() => loadConfig(true), [loadConfig]);

  useEffect(() => {
    loadConfig();
  }, [loadConfig]);

  const handleTest = async (providerId: string) => {
    setTestingProvider(providerId);
    try {
      const res = (await api.models.test(providerId)) as unknown as HealthResult;
      setTestResults((prev) => ({ ...prev, [providerId]: res }));
      // Refresh config to pick up updated health status
      await reloadConfig();
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
      await reloadConfig();
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
      await reloadConfig();
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
        <Button variant="outline" size="sm" onClick={() => loadConfig()}>
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
        </div>
        <div className="flex items-center gap-2">
          <Button variant="outline" size="sm" onClick={() => loadConfig()}>
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
          <div className="flex flex-col gap-4">
            {config.providers.map((p) => (
              <ProviderCard
                key={p.id}
                provider={p}
                testing={testingProvider === p.id}
                fetching={fetchingProvider === p.id}
                testResult={testResults[p.id] ?? null}
                onTest={() => handleTest(p.id)}
                onFetch={() => handleFetch(p.id)}
                onSaved={reloadConfig}
              />
            ))}
          </div>
        )}
      </div>

      <Separator />

      <TierTaskEditor
        tiers={tiers}
        taskEntries={taskEntries}
        providers={config.providers}
        onSaved={reloadConfig}
      />
    </div>
  );
}
