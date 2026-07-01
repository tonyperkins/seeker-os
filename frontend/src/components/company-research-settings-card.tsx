"use client";

import { useState, useEffect, useCallback } from "react";
import { Loader2, CheckCircle2, AlertCircle, FlaskConical, Settings2, Save } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Textarea } from "@/components/ui/textarea";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { CollapsibleCard } from "@/components/ui/collapsible-card";
import {
  api,
  type RetrievalSettings,
  type RetrievalSettingsUpdate,
} from "@/lib/api";

export function CompanyResearchSettingsCard() {
  const [settings, setSettings] = useState<RetrievalSettings | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<string | null>(null);

  // Form fields
  const [providerType, setProviderType] = useState("");
  const [apiKey, setApiKey] = useState("");
  const [maxResults, setMaxResults] = useState(5);
  const [timeoutSeconds, setTimeoutSeconds] = useState(15);
  const [fundingTemplate, setFundingTemplate] = useState("");
  const [sentimentTemplate, setSentimentTemplate] = useState("");
  const [confidenceFloor, setConfidenceFloor] = useState(0.3);
  const [stalenessMonths, setStalenessMonths] = useState(18);
  const [sourceTrustOrder, setSourceTrustOrder] = useState("");
  const [userAgent, setUserAgent] = useState("");

  // Test connection
  const [testing, setTesting] = useState(false);
  const [testResult, setTestResult] = useState<{ ok: boolean; message: string } | null>(null);

  const loadSettings = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const s = await api.companyResearchSettings.get();
      setSettings(s);
      setProviderType(s.provider_type || "");
      setMaxResults(s.max_results);
      setTimeoutSeconds(s.timeout_seconds);
      setFundingTemplate(s.funding_query_template);
      setSentimentTemplate(s.sentiment_query_template);
      setConfidenceFloor(s.confidence_floor);
      setStalenessMonths(s.staleness_months);
      setSourceTrustOrder(s.source_trust_order.join("\n"));
      setUserAgent(s.user_agent);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to load settings");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    loadSettings();
  }, [loadSettings]);

  const handleSave = async () => {
    setSaving(true);
    setSaveMsg(null);
    setError(null);
    try {
      const update: RetrievalSettingsUpdate = {
        provider_type: providerType,
        max_results: maxResults,
        timeout_seconds: timeoutSeconds,
        funding_query_template: fundingTemplate,
        sentiment_query_template: sentimentTemplate,
        confidence_floor: confidenceFloor,
        staleness_months: stalenessMonths,
        source_trust_order: sourceTrustOrder
          .split("\n")
          .map((s) => s.trim())
          .filter(Boolean),
        user_agent: userAgent || undefined,
      };
      if (apiKey) {
        update.api_key = apiKey;
      }
      const res = await api.companyResearchSettings.update(update);
      setSaveMsg(res.message);
      setApiKey("");
      await loadSettings();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save settings");
    } finally {
      setSaving(false);
    }
  };

  const handleTest = async () => {
    setTesting(true);
    setTestResult(null);
    try {
      const res = await api.companyResearchSettings.testConnection();
      setTestResult(res);
    } catch (e) {
      setTestResult({
        ok: false,
        message: e instanceof Error ? e.message : "Test failed",
      });
    } finally {
      setTesting(false);
    }
  };

  if (loading) {
    return (
      <CollapsibleCard
        icon={Settings2}
        title="Company Research"
        description="Configure live web search for funding and sentiment signals."
      >
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          <Loader2 className="size-4 animate-spin" />
          Loading...
        </div>
      </CollapsibleCard>
    );
  }

  return (
    <CollapsibleCard
      icon={Settings2}
      title="Company Research"
      description="Configure live web search for funding and sentiment signals."
    >
      <div className="flex flex-col gap-4">
        {error && (
          <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            <AlertCircle className="mt-0.5 size-3.5 shrink-0" />
            <span>{error}</span>
          </div>
        )}

        {/* Provider type */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cr-provider">Retrieval Provider</Label>
          <Select value={providerType} onValueChange={(v) => setProviderType(v ?? "")}>
            <SelectTrigger id="cr-provider">
              <SelectValue placeholder="Select provider" />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="">None (off)</SelectItem>
              <SelectItem value="tavily">Tavily</SelectItem>
            </SelectContent>
          </Select>
          <p className="text-xs text-muted-foreground">
            Choose a web search provider for live funding and sentiment data. &quot;None&quot; disables retrieval.
          </p>
        </div>

        {/* API key — write-only */}
        <div className="flex flex-col gap-1.5">
          <Label htmlFor="cr-api-key">API Key</Label>
          <div className="flex items-center gap-2">
            <Input
              id="cr-api-key"
              type="password"
              placeholder={settings?.api_key_configured ? "•••••••• (configured)" : "Enter API key"}
              value={apiKey}
              onChange={(e) => setApiKey(e.target.value)}
            />
            {settings?.api_key_configured && !apiKey && (
              <span className="flex items-center gap-1 text-xs text-emerald-600 dark:text-emerald-400 whitespace-nowrap">
                <CheckCircle2 className="size-3.5" />
                Configured
              </span>
            )}
          </div>
          <p className="text-xs text-muted-foreground">
            Stored securely in .env — never written to the config file. Leave blank to keep existing key.
          </p>
        </div>

        {/* Test connection */}
        <div className="flex items-center gap-3">
          <Button variant="outline" size="sm" onClick={handleTest} disabled={testing || !providerType}>
            {testing ? <Loader2 className="size-4 animate-spin" /> : <FlaskConical className="size-4" />}
            {testing ? "Testing..." : "Test Connection"}
          </Button>
          {testResult && (
            <span
              className={`text-xs flex items-center gap-1 ${
                testResult.ok
                  ? "text-emerald-600 dark:text-emerald-400"
                  : "text-destructive"
              }`}
            >
              {testResult.ok ? <CheckCircle2 className="size-3.5" /> : <AlertCircle className="size-3.5" />}
              {testResult.message}
            </span>
          )}
        </div>

        {/* Save button for primary fields */}
        <div className="flex items-center gap-3">
          <Button onClick={handleSave} disabled={saving}>
            {saving ? <Loader2 className="animate-spin" /> : <Save />}
            {saving ? "Saving..." : "Save Settings"}
          </Button>
          {saveMsg && (
            <span className="flex items-center gap-1.5 text-sm text-emerald-600 dark:text-emerald-400">
              <CheckCircle2 className="size-4" />
              {saveMsg}
            </span>
          )}
        </div>

        {/* Advanced settings — collapsible within the card */}
        <details className="mt-2">
          <summary className="cursor-pointer text-sm font-medium text-muted-foreground hover:text-foreground">
            Advanced settings
          </summary>
          <div className="mt-3 flex flex-col gap-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="cr-max-results">Max Results</Label>
                <Input
                  id="cr-max-results"
                  type="number"
                  min={1}
                  max={20}
                  value={maxResults}
                  onChange={(e) => setMaxResults(Number(e.target.value))}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="cr-timeout">Timeout (seconds)</Label>
                <Input
                  id="cr-timeout"
                  type="number"
                  min={5}
                  max={60}
                  value={timeoutSeconds}
                  onChange={(e) => setTimeoutSeconds(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="cr-funding-template">Funding Query Template</Label>
              <Input
                id="cr-funding-template"
                value={fundingTemplate}
                onChange={(e) => setFundingTemplate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{"{company} is replaced with the company name."}</p>
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="cr-sentiment-template">Sentiment Query Template</Label>
              <Input
                id="cr-sentiment-template"
                value={sentimentTemplate}
                onChange={(e) => setSentimentTemplate(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">{"{company} is replaced with the company name."}</p>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="flex flex-col gap-1">
                <Label htmlFor="cr-confidence-floor">Confidence Floor</Label>
                <Input
                  id="cr-confidence-floor"
                  type="number"
                  step={0.1}
                  min={0}
                  max={1}
                  value={confidenceFloor}
                  onChange={(e) => setConfidenceFloor(Number(e.target.value))}
                />
              </div>
              <div className="flex flex-col gap-1">
                <Label htmlFor="cr-staleness">Staleness (months)</Label>
                <Input
                  id="cr-staleness"
                  type="number"
                  min={1}
                  max={60}
                  value={stalenessMonths}
                  onChange={(e) => setStalenessMonths(Number(e.target.value))}
                />
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="cr-trust-order">Source Trust Order (one domain per line)</Label>
              <Textarea
                id="cr-trust-order"
                rows={5}
                value={sourceTrustOrder}
                onChange={(e) => setSourceTrustOrder(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                Domains listed first are ranked higher. Ordering only — no filtering.
              </p>
            </div>

            <div className="flex flex-col gap-1">
              <Label htmlFor="cr-user-agent">User-Agent</Label>
              <Input
                id="cr-user-agent"
                value={userAgent}
                onChange={(e) => setUserAgent(e.target.value)}
              />
              <p className="text-xs text-muted-foreground">
                HTTP User-Agent for Wikipedia/Wikidata requests. No personal handles.
              </p>
            </div>
          </div>
        </details>
      </div>
    </CollapsibleCard>
  );
}
