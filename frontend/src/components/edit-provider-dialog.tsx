"use client";

import { useState } from "react";
import { Settings2, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  DialogClose,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api, type ProviderInfoResponse } from "@/lib/api";

export function EditProviderDialog({
  provider,
  onSaved,
}: {
  provider: ProviderInfoResponse;
  onSaved: () => void;
}) {
  const [open, setOpen] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Form fields — initialized from provider, reset on open
  const [label, setLabel] = useState(provider.label);
  const [baseUrl, setBaseUrl] = useState(provider.base_url ?? "");
  const [enabled, setEnabled] = useState(provider.enabled);
  const [autoFetch, setAutoFetch] = useState(provider.auto_fetch_models);
  const [authMethod, setAuthMethod] = useState(provider.auth_method);
  const [oauthTokenPath, setOauthTokenPath] = useState(provider.oauth_token_path ?? "");
  const [apiKey, setApiKey] = useState("");

  function handleOpenChange(nextOpen: boolean) {
    if (nextOpen) {
      // Reset form to current provider values when opening
      setLabel(provider.label);
      setBaseUrl(provider.base_url ?? "");
      setEnabled(provider.enabled);
      setAutoFetch(provider.auto_fetch_models);
      setAuthMethod(provider.auth_method);
      setOauthTokenPath(provider.oauth_token_path ?? "");
      setApiKey("");
      setError(null);
    }
    setOpen(nextOpen);
  }

  async function handleSave() {
    setSaving(true);
    setError(null);
    try {
      const body: Record<string, unknown> = {
        label,
        enabled,
        auto_fetch_models: autoFetch,
        auth_method: authMethod,
      };

      if (provider.type === "openai_compatible") {
        body.base_url = baseUrl;
      }

      if (authMethod === "oauth") {
        body.oauth_token_path = oauthTokenPath;
      }

      // Only send API key if user entered a new one
      if (apiKey.trim()) {
        body.api_key = apiKey.trim();
      }

      await api.models.updateProvider(provider.id, body);
      setOpen(false);
      onSaved();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to save provider settings");
    } finally {
      setSaving(false);
    }
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogTrigger
        render={
          <Button size="sm" variant="ghost">
            <Settings2 className="h-3.5 w-3.5" />
            Edit
          </Button>
        }
      />
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>Edit {provider.label}</DialogTitle>
          <DialogDescription>
            Configure provider settings. Changes are saved to providers.yml.
          </DialogDescription>
        </DialogHeader>

        {error && (
          <div className="rounded-md bg-destructive/10 p-2.5 text-xs text-destructive">
            {error}
          </div>
        )}

        <div className="flex flex-col gap-4">
          {/* Label */}
          <div className="flex flex-col gap-1.5">
            <Label htmlFor="provider-label">Label</Label>
            <Input
              id="provider-label"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
            />
          </div>

          {/* Base URL (only for openai_compatible) */}
          {provider.type === "openai_compatible" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="provider-base-url">Base URL</Label>
              <Input
                id="provider-base-url"
                value={baseUrl}
                onChange={(e) => setBaseUrl(e.target.value)}
                placeholder="https://gateway.example.com/v1"
              />
            </div>
          )}

          {/* Auth method (only for anthropic) */}
          {provider.type === "anthropic" && (
            <div className="flex flex-col gap-1.5">
              <Label>Authentication Method</Label>
              <div className="flex gap-2">
                <button
                  type="button"
                  onClick={() => setAuthMethod("api_key")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    authMethod === "api_key"
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  API Key
                </button>
                <button
                  type="button"
                  onClick={() => setAuthMethod("oauth")}
                  className={`flex-1 rounded-lg border px-3 py-2 text-sm transition-colors ${
                    authMethod === "oauth"
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:bg-muted/50"
                  }`}
                >
                  OAuth Token
                </button>
              </div>
            </div>
          )}

          {/* API Key field */}
          {authMethod === "api_key" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="provider-api-key">
                API Key
                {provider.api_key_set && (
                  <span className="ml-2 text-xs font-normal text-muted-foreground">
                    (currently set — leave blank to keep)
                  </span>
                )}
              </Label>
              <Input
                id="provider-api-key"
                type="password"
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
                placeholder={provider.api_key_set ? "••••••••" : "Enter API key"}
              />
              <p className="text-xs text-muted-foreground">
                Stored in .env as ${provider.id.toUpperCase()}_API_KEY
              </p>
            </div>
          )}

          {/* OAuth token path */}
          {authMethod === "oauth" && (
            <div className="flex flex-col gap-1.5">
              <Label htmlFor="provider-oauth-path">OAuth Token File Path</Label>
              <Input
                id="provider-oauth-path"
                value={oauthTokenPath}
                onChange={(e) => setOauthTokenPath(e.target.value)}
                placeholder="~/.hermes/.anthropic_oauth.json"
              />
              <p className="text-xs text-muted-foreground">
                Path to a JSON file with an <code>accessToken</code> field (e.g. from
                Claude CLI login)
              </p>
            </div>
          )}

          {/* Toggles */}
          <div className="flex flex-col gap-3">
            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
                className="size-4 rounded border-border"
              />
              Enabled
            </label>

            <label className="flex items-center gap-2 text-sm">
              <input
                type="checkbox"
                checked={autoFetch}
                onChange={(e) => setAutoFetch(e.target.checked)}
                className="size-4 rounded border-border"
              />
              Auto-fetch models from provider API
            </label>
          </div>
        </div>

        <DialogFooter>
          <DialogClose render={<Button variant="outline" />}>Cancel</DialogClose>
          <Button disabled={saving} onClick={handleSave}>
            {saving ? <Loader2 className="h-4 w-4 animate-spin" /> : <Settings2 className="h-4 w-4" />}
            Save Changes
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
