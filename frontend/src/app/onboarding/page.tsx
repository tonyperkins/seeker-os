"use client";

import { useState, useCallback, useEffect } from "react";
import { useRouter } from "next/navigation";
import {
  Server,
  Upload,
  Sparkles,
  SlidersHorizontal,
  CheckCircle2,
  Loader2,
  ArrowRight,
  ArrowLeft,
  RefreshCw,
  AlertCircle,
  KeyRound,
} from "lucide-react";
import {
  Card,
  CardHeader,
  CardTitle,
  CardDescription,
  CardContent,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { MasterResumeUpload } from "@/components/master-resume-upload";
import { AnthropicAuthDialog } from "@/components/anthropic-auth-dialog";
import { ProfileForm } from "@/components/profile-form";
import { FilterForm } from "@/components/filter-form";
import {
  api,
  type ProvidersConfigResponse,
  type MasterResumeInfo,
  type ProfileData,
  type FiltersData,
  type ResumeParseResult,
} from "@/lib/api";
import { cn } from "@/lib/utils";

const STEPS = [
  { key: "provider", label: "LLM Provider", icon: Server },
  { key: "resume", label: "Upload Resume", icon: Upload },
  { key: "parse", label: "Parse Resume", icon: Sparkles },
  { key: "review", label: "Review Config", icon: SlidersHorizontal },
  { key: "done", label: "Complete", icon: CheckCircle2 },
] as const;

export default function OnboardingPage() {
  const router = useRouter();
  const [currentStep, setCurrentStep] = useState(0);
  const [loading, setLoading] = useState(true);

  // State for each step
  const [providers, setProviders] = useState<ProvidersConfigResponse | null>(null);
  const [resumeInfo, setResumeInfo] = useState<MasterResumeInfo | null>(null);
  const [profile, setProfile] = useState<ProfileData | null>(null);
  const [filters, setFilters] = useState<FiltersData | null>(null);
  const [parseResult, setParseResult] = useState<ResumeParseResult | null>(null);

  // Load initial state
  useEffect(() => {
    Promise.all([
      api.models.getConfig().catch(() => null),
      api.resumes.getMaster().catch(() => null),
      api.profile.get().catch(() => null),
      api.filters.get().catch(() => null),
    ]).then(([p, r, prof, filt]) => {
      setProviders(p);
      setResumeInfo(r);
      setProfile(prof);
      setFilters(filt);
      setLoading(false);

      // Auto-advance to the first incomplete step
      const hasProvider = (p?.providers ?? []).some(
        (prov) => prov.enabled && prov.api_key_set && prov.models.length > 0,
      );
      const pTiers = p?.tiers ?? {};
      const pList = p?.providers ?? [];
      const tierOk = (t: typeof pTiers[keyof typeof pTiers]) => {
        if (!t?.model || !t?.provider) return false;
        const prov = pList.find((pv) => pv.id === t.provider);
        return !!prov && prov.api_key_set && prov.models.some((m) => m.id === t.model);
      };
      const tiersConfigured = tierOk(pTiers.heavy) && tierOk(pTiers.moderate) && tierOk(pTiers.light);
      const providerDone = hasProvider && tiersConfigured;
      const hasResume = r?.exists ?? false;
      const isProfileConfigured = prof?.user && prof.user.name !== "Your Name" && prof.user.email !== "you@example.com";

      if (providerDone && hasResume && isProfileConfigured) {
        setCurrentStep(4); // Done
      } else if (providerDone && hasResume) {
        setCurrentStep(2); // Parse
      } else if (providerDone) {
        setCurrentStep(1); // Upload
      } else {
        setCurrentStep(0); // Provider
      }
    });
  }, []);

  const refreshProviders = useCallback(async () => {
    const p = await api.models.getConfig().catch(() => null);
    setProviders(p);
    return p;
  }, []);

  const refreshResume = useCallback(async () => {
    const r = await api.resumes.getMaster().catch(() => null);
    setResumeInfo(r);
    return r;
  }, []);

  const refreshProfile = useCallback(async () => {
    const [prof, filt] = await Promise.all([
      api.profile.get().catch(() => null),
      api.filters.get().catch(() => null),
    ]);
    setProfile(prof);
    setFilters(filt);
    return { prof, filt };
  }, []);

  const hasProvider = (providers?.providers ?? []).some(
    (p) => p.enabled && p.api_key_set && p.models.length > 0,
  );
  const hasResume = resumeInfo?.exists ?? false;
  const isProfileConfigured = profile?.user && profile.user.name !== "Your Name" && profile.user.email !== "you@example.com";

  // Tiers are only "configured" if each tier's assigned provider is connected
  // AND the assigned model is in that provider's available models list.
  // This prevents the pre-filled example template from counting as configured.
  const tiers = providers?.tiers ?? {};
  const providerList = providers?.providers ?? [];
  const tierIsValid = (tier: typeof tiers[keyof typeof tiers]) => {
    if (!tier?.model || !tier?.provider) return false;
    const prov = providerList.find((p) => p.id === tier.provider);
    return !!prov && prov.api_key_set && prov.models.some((m) => m.id === tier.model);
  };
  const tiersConfigured = tierIsValid(tiers.heavy) && tierIsValid(tiers.moderate) && tierIsValid(tiers.light);
  const providerStepComplete = hasProvider && tiersConfigured;

  const canAdvance = [
    providerStepComplete,  // step 0
    hasResume,             // step 1
    isProfileConfigured,   // step 2 (parse saves to config)
    isProfileConfigured,   // step 3 (review)
    true,                  // step 4 (done)
  ];

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center">
        <Loader2 className="size-8 animate-spin text-muted-foreground" />
      </div>
    );
  }

  return (
    <div className="min-h-screen bg-background">
      {/* Top bar with logo */}
      <div className="border-b border-border bg-card">
        <div className="mx-auto max-w-3xl px-6 py-4 flex items-center justify-between">
          <div>
            <h1 className="text-xl font-bold tracking-tight">Seeker OS</h1>
            <p className="text-xs text-muted-foreground">Setup Wizard</p>
          </div>
          <Button variant="ghost" size="sm" onClick={() => router.push("/")}>
            Skip for now
          </Button>
        </div>
      </div>

      {/* Step indicator — anchored at top */}
      <div className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto max-w-3xl px-6 py-4">
          <div className="flex items-center justify-between">
            {STEPS.map((step, i) => {
              const Icon = step.icon;
              const isComplete = i < currentStep || (i === currentStep && canAdvance[i]);
              const isCurrent = i === currentStep;
              const isLocked = i > currentStep;

              return (
                <div key={step.key} className="flex items-center flex-1 last:flex-none">
                  <div className="flex flex-col items-center gap-1.5">
                    <div
                      className={cn(
                        "flex size-10 items-center justify-center rounded-full border-2 transition-all",
                        isComplete && "border-emerald-500 bg-emerald-500/10",
                        isCurrent && !isComplete && "border-primary bg-primary/10",
                        isLocked && "border-muted bg-muted/30 opacity-50",
                      )}
                    >
                      {isComplete ? (
                        <CheckCircle2 className="size-5 text-emerald-500" />
                      ) : (
                        <Icon className={cn("size-5", isCurrent ? "text-primary" : "text-muted-foreground")} />
                      )}
                    </div>
                    <span className={cn(
                      "text-xs font-medium whitespace-nowrap",
                      isCurrent ? "text-foreground" : "text-muted-foreground",
                    )}>
                      {step.label}
                    </span>
                  </div>
                  {i < STEPS.length - 1 && (
                    <div className={cn(
                      "h-0.5 flex-1 mx-2 transition-colors",
                      i < currentStep ? "bg-emerald-500" : "bg-border",
                    )} />
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>

      {/* Step content */}
      <div className="mx-auto max-w-3xl px-6 py-8">
        {currentStep === 0 && (
          <ProviderStep
            providers={providers}
            hasProvider={hasProvider}
            tiersConfigured={tiersConfigured}
            onRefresh={refreshProviders}
            onNext={() => setCurrentStep(1)}
          />
        )}
        {currentStep === 1 && (
          <ResumeStep
            hasResume={hasResume}
            onRefresh={refreshResume}
            onBack={() => setCurrentStep(0)}
            onNext={() => setCurrentStep(2)}
          />
        )}
        {currentStep === 2 && (
          <ParseStep
            hasResume={hasResume}
            parseResult={parseResult}
            onParsed={(result) => {
              setParseResult(result);
              refreshProfile();
            }}
            onBack={() => setCurrentStep(1)}
            onNext={() => setCurrentStep(3)}
          />
        )}
        {currentStep === 3 && (
          <ReviewStep
            profile={profile}
            filters={filters}
            parseResult={parseResult}
            isProfileConfigured={!!isProfileConfigured}
            onBack={() => setCurrentStep(2)}
            onNext={() => setCurrentStep(4)}
          />
        )}
        {currentStep === 4 && (
          <DoneStep onGoToDashboard={() => router.push("/")} />
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 1: Provider configuration
// ---------------------------------------------------------------------------

function ProviderStep({
  providers,
  hasProvider,
  tiersConfigured,
  onRefresh,
  onNext,
}: {
  providers: ProvidersConfigResponse | null;
  hasProvider: boolean;
  tiersConfigured: boolean;
  onRefresh: () => Promise<ProvidersConfigResponse | null>;
  onNext: () => void;
}) {
  const [authOpen, setAuthOpen] = useState(false);
  const [fetchingProvider, setFetchingProvider] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [savingTiers, setSavingTiers] = useState(false);
  const [editingProvider, setEditingProvider] = useState<string | null>(null);

  const allProviders = providers?.providers ?? [];
  const enabledProviders = allProviders.filter((p) => p.enabled);
  const tiers = providers?.tiers ?? {};

  const handleAuthSuccess = useCallback(async () => {
    setAuthOpen(false);
    setError(null);
    const p = await onRefresh();
    const anthropic = p?.providers.find((prov) => prov.type === "anthropic");
    if (anthropic) {
      setFetchingProvider(anthropic.id);
      try {
        await api.models.fetch(anthropic.id);
        await onRefresh();
      } catch (e) {
        setError(e instanceof Error ? e.message : "Failed to fetch models");
      } finally {
        setFetchingProvider(null);
      }
    }
  }, [onRefresh]);

  const handleFetchModels = useCallback(async (providerId: string) => {
    setFetchingProvider(providerId);
    setError(null);
    try {
      await api.models.fetch(providerId);
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to fetch models");
    } finally {
      setFetchingProvider(null);
    }
  }, [onRefresh]);

  const handleEnableProvider = useCallback(async (providerId: string, enabled: boolean) => {
    setError(null);
    try {
      await api.models.updateProvider(providerId, { enabled });
      await onRefresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to update provider");
    }
  }, [onRefresh]);

  const handleSaveTiers = useCallback(async () => {
    setSavingTiers(true);
    setError(null);
    try {
      // Find the first provider with models and auto-assign tiers
      const providerWithModels = enabledProviders.find((p) => p.models.length > 0);
      if (providerWithModels) {
        const models = providerWithModels.models;
        const heavy = models.find((m) => m.id.includes("opus")) ??
                      models.find((m) => m.id.includes("gpt-4")) ??
                      models.find((m) => m.id.includes("llama")) ??
                      models[0];
        const moderate = models.find((m) => m.id.includes("sonnet")) ??
                         models.find((m) => m.id.includes("gpt-4o-mini")) ??
                         models.find((m) => m.id.includes("llama")) ??
                         models[0];
        const light = models.find((m) => m.id.includes("haiku")) ??
                      models.find((m) => m.id.includes("mini")) ??
                      models.find((m) => m.id.includes("llama")) ??
                      models[0];
        await Promise.all([
          api.models.updateTier("heavy", providerWithModels.id, heavy.id),
          api.models.updateTier("moderate", providerWithModels.id, moderate.id),
          api.models.updateTier("light", providerWithModels.id, light.id),
        ]);
        await onRefresh();
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save tier mappings");
    } finally {
      setSavingTiers(false);
    }
  }, [enabledProviders, onRefresh]);

  // Tiers need attention if any connected provider has models but the tier
  // mappings don't point to valid, available models on connected providers.
  const checkTier = (tier: typeof tiers[keyof typeof tiers]) => {
    if (!tier?.model || !tier?.provider) return false;
    const prov = enabledProviders.find((p) => p.id === tier.provider);
    return !!prov && prov.models.some((m) => m.id === tier.model);
  };
  const needsTiers = hasProvider && enabledProviders.length > 0 &&
    !(checkTier(tiers.heavy) && checkTier(tiers.moderate) && checkTier(tiers.light));

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Configure an LLM Provider</h2>
        <p className="text-sm text-muted-foreground mt-1">
          Seeker OS needs an LLM to parse resumes, score jobs, and generate tailored resumes.
          Connect at least one provider below.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      {/* Provider cards */}
      {allProviders.map((provider) => (
        <ProviderCard
          key={provider.id}
          provider={provider}
          fetching={fetchingProvider === provider.id}
          onFetchModels={() => handleFetchModels(provider.id)}
          onToggleEnabled={(enabled) => handleEnableProvider(provider.id, enabled)}
          onConnectAnthropic={() => setAuthOpen(true)}
          onEdit={() => setEditingProvider(provider.id)}
          editingOpen={editingProvider === provider.id}
          onEditClose={() => setEditingProvider(null)}
          onSaved={onRefresh}
        />
      ))}

      {/* Tier mappings — show when any provider has models */}
      {hasProvider && enabledProviders.some((p) => p.models.length > 0) && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="size-4" />
              Tier Mappings
            </CardTitle>
            <CardDescription>
              Assign models to each tier: heavy (resume generation), moderate (analysis), light (validation).
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-3">
            {needsTiers && (
              <Button size="sm" variant="outline" onClick={handleSaveTiers} disabled={savingTiers}>
                {savingTiers ? <Loader2 className="size-3.5 animate-spin" /> : null}
                Auto-assign tiers
              </Button>
            )}
            <div className="grid gap-2">
              {(["heavy", "moderate", "light"] as const).map((tier) => (
                <TierSelect
                  key={tier}
                  tier={tier}
                  providers={providers!}
                  currentModel={tiers[tier]?.model ?? ""}
                  onSaved={onRefresh}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      <AnthropicAuthDialog
        key={authOpen ? "open" : "closed"}
        open={authOpen}
        onOpenChange={setAuthOpen}
        onSuccess={handleAuthSuccess}
      />

      {/* Continue button */}
      <div className="flex flex-col items-end gap-2">
        {!hasProvider && (
          <p className="text-xs text-muted-foreground">Connect and enable at least one provider with models.</p>
        )}
        {hasProvider && !tiersConfigured && (
          <p className="text-xs text-muted-foreground">Assign models to all three tiers (heavy, moderate, light) to continue.</p>
        )}
        <Button onClick={onNext} disabled={!hasProvider || !tiersConfigured} size="lg">
          Continue
          <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

function ProviderCard({
  provider,
  fetching,
  onFetchModels,
  onToggleEnabled,
  onConnectAnthropic,
  onEdit,
  editingOpen,
  onEditClose,
  onSaved,
}: {
  provider: ProvidersConfigResponse["providers"][number];
  fetching: boolean;
  onFetchModels: () => void;
  onToggleEnabled: (enabled: boolean) => void;
  onConnectAnthropic: () => void;
  onEdit: () => void;
  editingOpen: boolean;
  onEditClose: () => void;
  onSaved: () => Promise<ProvidersConfigResponse | null>;
}) {
  const isAnthropic = provider.type === "anthropic";
  const connected = provider.api_key_set;
  const hasModels = provider.models.length > 0;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div>
            <CardTitle className="flex items-center gap-2 text-base">
              <Server className="size-4" />
              {provider.label}
            </CardTitle>
            <CardDescription className="mt-1">
              {isAnthropic
                ? "Claude Pro/Max subscription via OAuth, or API key"
                : `OpenAI-compatible gateway at ${provider.base_url ?? "—"}`}
            </CardDescription>
          </div>
          <label className="flex items-center gap-2 text-xs">
            <input
              type="checkbox"
              checked={provider.enabled}
              onChange={(e) => onToggleEnabled(e.target.checked)}
              className="size-4 rounded border-border"
            />
            Enabled
          </label>
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {/* Connection status */}
        <div className="flex items-center justify-between rounded-md border border-border p-3">
          <div className="flex items-center gap-3">
            {connected ? (
              <CheckCircle2 className="size-5 text-emerald-500" />
            ) : (
              <KeyRound className="size-5 text-muted-foreground" />
            )}
            <div>
              <p className="text-sm font-medium">
                {connected ? "Connected" : "Not connected"}
              </p>
              <p className="text-xs text-muted-foreground">
                {provider.auth_method === "oauth" ? "OAuth token" : "API key"}
                {provider.base_url && ` · ${provider.base_url}`}
              </p>
            </div>
          </div>
          {isAnthropic ? (
            <Button
              variant={connected ? "outline" : "default"}
              size="sm"
              onClick={onConnectAnthropic}
            >
              <KeyRound className="size-3.5" />
              {connected ? "Re-authorize" : "Connect Account"}
            </Button>
          ) : (
            <Button variant="outline" size="sm" onClick={onEdit}>
              <KeyRound className="size-3.5" />
              Configure
            </Button>
          )}
        </div>

        {/* Models status */}
        {provider.enabled && (
          <div className="flex items-center justify-between rounded-md border border-border p-3">
            <div className="flex items-center gap-3">
              {hasModels ? (
                <CheckCircle2 className="size-5 text-emerald-500" />
              ) : (
                <Loader2 className="size-5 text-muted-foreground" />
              )}
              <div>
                <p className="text-sm font-medium">
                  {hasModels
                    ? `${provider.models.length} models available`
                    : "No models fetched yet"}
                </p>
                <p className="text-xs text-muted-foreground">
                  {provider.models.slice(0, 3).map((m) => m.id).join(", ")}
                </p>
              </div>
            </div>
            {provider.auto_fetch_models && (
              <Button
                variant="outline"
                size="sm"
                onClick={onFetchModels}
                disabled={fetching || !connected}
              >
                {fetching ? <Loader2 className="size-3.5 animate-spin" /> : <RefreshCw className="size-3.5" />}
                Fetch Models
              </Button>
            )}
          </div>
        )}

        {/* Edit dialog for non-Anthropic providers */}
        {!isAnthropic && editingOpen && (
          <EditProviderInline
            provider={provider}
            onClose={onEditClose}
            onSaved={onSaved}
          />
        )}
      </CardContent>
    </Card>
  );
}

function EditProviderInline({
  provider,
  onClose,
  onSaved,
}: {
  provider: ProvidersConfigResponse["providers"][number];
  onClose: () => void;
  onSaved: () => Promise<ProvidersConfigResponse | null>;
}) {
  const [label, setLabel] = useState(provider.label);
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [apiKey, setApiKey] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSave = useCallback(async () => {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        label,
        enabled: true,
        auto_fetch_models: true,
        auth_method: "api_key",
        base_url: baseUrl,
      };
      if (apiKey.trim()) {
        body.api_key = apiKey.trim();
      }
      await api.models.updateProvider(provider.id, body);
      await onSaved();
      onClose();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save");
    } finally {
      setSaving(false);
    }
  }, [label, baseUrl, apiKey, provider.id, onSaved, onClose]);

  return (
    <div className="rounded-md border border-border p-4 space-y-3">
      <div className="flex items-center justify-between">
        <p className="text-sm font-medium">Configure {provider.label}</p>
        <Button variant="ghost" size="sm" onClick={onClose}>Cancel</Button>
      </div>
      {error && (
        <p className="text-xs text-destructive">{error}</p>
      )}
      <div className="space-y-2">
        <label className="text-xs text-muted-foreground">Label</label>
        <input
          value={label}
          onChange={(e) => setLabel(e.target.value)}
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm"
        />
      </div>
      <div className="space-y-2">
        <label className="text-xs text-muted-foreground">Base URL</label>
        <input
          value={baseUrl}
          onChange={(e) => setBaseUrl(e.target.value)}
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm font-mono"
          placeholder="https://gateway.example.com/v1"
        />
      </div>
      <div className="space-y-2">
        <label className="text-xs text-muted-foreground">
          API Key {provider.api_key_set && "(currently set — leave blank to keep)"}
        </label>
        <input
          type="password"
          value={apiKey}
          onChange={(e) => setApiKey(e.target.value)}
          className="h-8 w-full rounded-md border border-border bg-background px-2 text-sm"
          placeholder={provider.api_key_set ? "••••••••" : "Enter API key"}
        />
        <p className="text-xs text-muted-foreground">
          Stored in .env as ${provider.id.toUpperCase()}_API_KEY
        </p>
      </div>
      <Button onClick={handleSave} disabled={saving} size="sm" className="w-full">
        {saving ? <Loader2 className="size-3.5 animate-spin" /> : null}
        Save
      </Button>
    </div>
  );
}

function TierSelect({
  tier,
  providers,
  currentModel,
  onSaved,
}: {
  tier: string;
  providers: ProvidersConfigResponse;
  currentModel: string;
  onSaved: () => Promise<ProvidersConfigResponse | null>;
}) {
  // Only show providers that are connected and have fetched models available
  const availableProviders = providers.providers.filter((p) => p.api_key_set && p.models.length > 0);
  const savedTier = providers.tiers[tier as keyof typeof providers.tiers];

  // Derive the effective provider: use the saved one if it's available
  // (connected + has models), otherwise fall back to the first available.
  const savedProviderAvailable = !!savedTier?.provider && availableProviders.some((p) => p.id === savedTier.provider);
  const effectiveProvider = savedProviderAvailable
    ? savedTier!.provider
    : availableProviders[0]?.id ?? "";

  // Track user overrides (when they change the dropdown before auto-save completes)
  const [providerOverride, setProviderOverride] = useState<string | null>(null);
  const [modelOverride, setModelOverride] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // Use override if set, otherwise the derived value
  const provider = providerOverride ?? effectiveProvider;
  const providerInfo = providers.providers.find((p) => p.id === provider);
  const models = providerInfo?.models ?? [];

  // Derive effective model: use override if set, otherwise the saved model
  // if it's valid for the current provider, otherwise the first available model.
  const savedModelValid = currentModel && models.some((m) => m.id === currentModel);
  const effectiveModel = modelOverride
    ?? (savedModelValid ? currentModel : models[0]?.id ?? "");
  const model = effectiveModel;

  // Auto-save whenever provider or model changes (and we have valid values)
  const handleSave = useCallback(async (provId: string, modelId: string) => {
    if (!provId || !modelId) return;
    setSaving(true);
    try {
      await api.models.updateTier(tier, provId, modelId);
      await onSaved();
      // Clear overrides after save — the refreshed props become the source of truth
      setProviderOverride(null);
      setModelOverride(null);
    } finally {
      setSaving(false);
    }
  }, [tier, onSaved]);

  const handleProviderChange = (newProviderId: string) => {
    setProviderOverride(newProviderId);
    const newModels = providers.providers.find((p) => p.id === newProviderId)?.models ?? [];
    // Auto-select first model if current model isn't available for this provider
    const newModel = newModels.length > 0 && !newModels.some((m) => m.id === model)
      ? newModels[0].id
      : model;
    if (newModel !== model) setModelOverride(newModel);
    handleSave(newProviderId, newModel);
  };

  const handleModelChange = (newModelId: string) => {
    setModelOverride(newModelId);
    handleSave(provider, newModelId);
  };

  if (availableProviders.length === 0) {
    return (
      <div className="flex items-center gap-2">
        <Badge variant="outline" className="text-xs w-16 justify-center">{tier}</Badge>
        <p className="text-xs text-muted-foreground">No providers with models available yet.</p>
      </div>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <Badge variant="outline" className="text-xs w-16 justify-center">{tier}</Badge>
      <select
        value={provider}
        onChange={(e) => handleProviderChange(e.target.value)}
        disabled={saving}
        className="h-8 rounded-md border border-border bg-background px-2 text-xs font-mono flex-1"
      >
        {availableProviders.map((p) => (
          <option key={p.id} value={p.id}>{p.id}</option>
        ))}
      </select>
      <select
        value={model}
        onChange={(e) => handleModelChange(e.target.value)}
        disabled={saving || models.length === 0}
        className="h-8 rounded-md border border-border bg-background px-2 text-xs font-mono flex-1"
      >
        {models.length === 0 ? (
          <option value="">(no models)</option>
        ) : (
          models.map((m) => (
            <option key={m.id} value={m.id}>{m.id}</option>
          ))
        )}
      </select>
      {saving && <Loader2 className="size-3 animate-spin text-muted-foreground" />}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 2: Upload resume
// ---------------------------------------------------------------------------

function ResumeStep({
  hasResume,
  onRefresh,
  onBack,
  onNext,
}: {
  hasResume: boolean;
  onRefresh: () => Promise<MasterResumeInfo | null>;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Upload Your Master Resume</h2>
        <p className="text-sm text-muted-foreground mt-1">
          This resume is the source for all tailored resume generation. Upload your most
          comprehensive resume — we&apos;ll extract your profile data from it next.
        </p>
      </div>

      <Card>
        <CardContent className="pt-6">
          <MasterResumeUpload
            onUploaded={onRefresh}
            bare
          />
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft />
          Back
        </Button>
        <Button onClick={onNext} disabled={!hasResume} size="lg">
          Continue
          <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 3: Parse resume
// ---------------------------------------------------------------------------

function ParseStep({
  hasResume,
  parseResult,
  onParsed,
  onBack,
  onNext,
}: {
  hasResume: boolean;
  parseResult: ResumeParseResult | null;
  onParsed: (result: ResumeParseResult) => void;
  onBack: () => void;
  onNext: () => void;
}) {
  const [parsing, setParsing] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleParse = useCallback(async () => {
    setParsing(true);
    setError(null);
    try {
      const result = await api.resumes.parse();
      onParsed(result);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to parse resume");
    } finally {
      setParsing(false);
    }
  }, [onParsed]);

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Parse Your Resume</h2>
        <p className="text-sm text-muted-foreground mt-1">
          We&apos;ll use your configured LLM to extract contact info, experience, skills, and
          suggested filter parameters. This data is saved to your profile and filter config
          automatically — you&apos;ll review and edit it in the next step.
        </p>
      </div>

      {error && (
        <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
          <AlertCircle className="mt-0.5 size-4 shrink-0" />
          <span>{error}</span>
        </div>
      )}

      <Card>
        <CardContent className="pt-6">
          {parseResult ? (
            <div className="space-y-4">
              <div className="flex items-center gap-2 text-emerald-600 dark:text-emerald-400">
                <CheckCircle2 className="size-5" />
                <span className="font-medium">Resume parsed successfully!</span>
              </div>
              <div className="rounded-md border border-emerald-500/30 bg-emerald-500/5 p-4 space-y-2 text-sm">
                <div className="grid grid-cols-2 gap-2">
                  <div>
                    <span className="text-muted-foreground">Name:</span> {parseResult.contact.name}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Email:</span> {parseResult.contact.email}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Location:</span> {parseResult.contact.location}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Experience:</span> {parseResult.experience_years} years
                  </div>
                  <div>
                    <span className="text-muted-foreground">Current title:</span> {parseResult.current_title}
                  </div>
                  <div>
                    <span className="text-muted-foreground">Comp floor:</span> ${parseResult.suggested_comp_floor?.toLocaleString()}
                  </div>
                </div>
                <div>
                  <span className="text-muted-foreground">Key skills:</span>{" "}
                  {parseResult.key_skills.join(", ")}
                </div>
                <div>
                  <span className="text-muted-foreground">Suggested title patterns:</span>{" "}
                  {parseResult.suggested_title_positive.join(", ")}
                </div>
              </div>
              <p className="text-xs text-muted-foreground">
                This data has been saved to your config. Review and edit it in the next step.
              </p>
            </div>
          ) : (
            <div className="flex flex-col items-center gap-4 py-8">
              <Sparkles className="size-12 text-primary" />
              <p className="text-sm text-muted-foreground text-center max-w-md">
                Click the button below to extract your profile data from your master resume
                using your configured LLM.
              </p>
              <Button onClick={handleParse} disabled={parsing || !hasResume} size="lg">
                {parsing ? <Loader2 className="animate-spin" /> : <Sparkles />}
                {parsing ? "Parsing Resume..." : "Parse Resume"}
              </Button>
            </div>
          )}
        </CardContent>
      </Card>

      <div className="flex justify-between">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft />
          Back
        </Button>
        <Button onClick={onNext} disabled={!parseResult} size="lg">
          Review Config
          <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 4: Review profile & filters
// ---------------------------------------------------------------------------

function ReviewStep({
  profile,
  filters,
  parseResult,
  isProfileConfigured,
  onBack,
  onNext,
}: {
  profile: ProfileData | null;
  filters: FiltersData | null;
  parseResult: ResumeParseResult | null;
  isProfileConfigured: boolean;
  onBack: () => void;
  onNext: () => void;
}) {
  return (
    <div className="flex flex-col gap-6">
      <div>
        <h2 className="text-2xl font-bold tracking-tight">Review Your Profile & Filters</h2>
        <p className="text-sm text-muted-foreground mt-1">
          The parsed data has been saved to your config. Review and adjust anything below,
          then save your changes to continue.
        </p>
      </div>

      {profile && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="size-4" />
              Profile
            </CardTitle>
            <CardDescription>
              Contact info, compensation, experience, and instructions for resume generation.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <ProfileForm
              key={parseResult ? `parsed-${parseResult.contact.name}` : "review"}
              profile={profile}
              parseResult={parseResult}
            />
          </CardContent>
        </Card>
      )}

      {filters && (
        <Card>
          <CardHeader>
            <CardTitle className="flex items-center gap-2 text-base">
              <SlidersHorizontal className="size-4" />
              Filter Parameters
            </CardTitle>
            <CardDescription>
              Hard filters applied before JD fetch — title patterns, seniority, comp, and more.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <FilterForm
              key={parseResult ? `parsed-${parseResult.suggested_comp_floor}` : "review"}
              filters={filters}
              parseResult={parseResult}
            />
          </CardContent>
        </Card>
      )}

      <div className="flex justify-between">
        <Button variant="ghost" onClick={onBack}>
          <ArrowLeft />
          Back
        </Button>
        <Button onClick={onNext} size="lg">
          {isProfileConfigured ? "Complete Setup" : "Save & Continue"}
          <ArrowRight />
        </Button>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Step 5: Done
// ---------------------------------------------------------------------------

function DoneStep({ onGoToDashboard }: { onGoToDashboard: () => void }) {
  return (
    <div className="flex flex-col items-center gap-6 py-12">
      <div className="flex size-16 items-center justify-center rounded-full bg-emerald-500/10">
        <CheckCircle2 className="size-10 text-emerald-500" />
      </div>
      <div className="text-center space-y-2">
        <h2 className="text-2xl font-bold tracking-tight">Setup Complete!</h2>
        <p className="text-sm text-muted-foreground max-w-md">
          You&apos;re all set. Head to the dashboard to run the pipeline and start
          discovering jobs that match your profile.
        </p>
      </div>
      <Button onClick={onGoToDashboard} size="lg">
        Go to Dashboard
        <ArrowRight />
      </Button>
    </div>
  );
}
