"use client";

import { useState, useCallback } from "react";
import { ExternalLink, Loader2, CheckCircle2, AlertCircle, KeyRound } from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { api } from "@/lib/api";

export function AnthropicAuthDialog({
  open,
  onOpenChange,
  onSuccess,
}: {
  open: boolean;
  onOpenChange: (_open: boolean) => void;
  onSuccess?: () => void;
}) {
  const [step, setStep] = useState<"idle" | "initiating" | "waiting" | "done" | "error">("idle");
  const [exchanging, setExchanging] = useState(false);
  const [authUrl, setAuthUrl] = useState("");
  const [state, setState] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);

  // Reset when dialog opens — use key prop on parent for remount instead
  // of effect-based reset to avoid cascading renders

  const handleInitiate = useCallback(async () => {
    setStep("initiating");
    setError(null);
    try {
      const result = await api.models.oauthInitiate();
      setAuthUrl(result.auth_url);
      setState(result.state);
      setStep("waiting");
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to start OAuth flow");
      setStep("error");
    }
  }, []);

  const handleExchange = useCallback(async () => {
    if (!code.trim()) return;
    setExchanging(true);
    setError(null);
    try {
      await api.models.oauthCallback(code.trim(), state);
      setStep("done");
      onSuccess?.();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to exchange code for token");
      setStep("error");
    } finally {
      setExchanging(false);
    }
  }, [code, state, onSuccess]);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <KeyRound className="size-5" />
            Connect Anthropic Account
          </DialogTitle>
          <DialogDescription>
            Authorize Seeker OS to use your Claude Pro/Max subscription for LLM calls.
          </DialogDescription>
        </DialogHeader>

        <div className="flex flex-col gap-4 py-2">
          {step === "idle" && (
            <div className="flex flex-col gap-3">
              <p className="text-sm text-muted-foreground">
                This will open Anthropic&apos;s authorization page in your browser.
                After authorizing, you&apos;ll receive a code to paste back here.
              </p>
              <Button onClick={handleInitiate} size="lg">
                <ExternalLink />
                Start Authorization
              </Button>
            </div>
          )}

          {step === "initiating" && (
            <div className="flex items-center justify-center py-6">
              <Loader2 className="size-6 animate-spin text-muted-foreground" />
            </div>
          )}

          {step === "waiting" && (
            <div className="flex flex-col gap-4">
              <div className="rounded-md border border-border p-3">
                <p className="text-xs font-medium text-muted-foreground mb-2">
                  Step 1: Open this URL in your browser
                </p>
                <div className="flex items-center gap-2">
                  <Input
                    value={authUrl}
                    readOnly
                    className="text-xs font-mono"
                    onClick={(e) => e.currentTarget.select()}
                  />
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={() => {
                      navigator.clipboard.writeText(authUrl);
                      window.open(authUrl, "_blank");
                    }}
                  >
                    <ExternalLink className="size-3.5" />
                    Open
                  </Button>
                </div>
              </div>

              <div className="rounded-md border border-border p-3">
                <p className="text-xs font-medium text-muted-foreground mb-2">
                  Step 2: After authorizing, paste the code here
                </p>
                <Label className="text-xs text-muted-foreground">Authorization code</Label>
                <Input
                  value={code}
                  onChange={(e) => setCode(e.target.value)}
                  placeholder="Paste code here..."
                  className="font-mono text-xs"
                  onKeyDown={(e) => e.key === "Enter" && handleExchange()}
                />
                <p className="text-xs text-muted-foreground mt-1">
                  The code looks like: <code className="font-mono">xxxxx#state</code>
                </p>
              </div>

              <Button onClick={handleExchange} disabled={!code.trim() || exchanging} size="lg">
                {exchanging ? <Loader2 className="animate-spin" /> : <KeyRound />}
                {exchanging ? "Exchanging..." : "Complete Authorization"}
              </Button>
            </div>
          )}

          {step === "done" && (
            <div className="flex flex-col items-center gap-3 py-4">
              <CheckCircle2 className="size-10 text-emerald-500" />
              <p className="text-sm font-medium">Successfully connected!</p>
              <p className="text-xs text-muted-foreground">
                Your Anthropic account is now authorized. You can close this dialog.
              </p>
            </div>
          )}

          {step === "error" && (
            <div className="flex flex-col gap-3">
              <div className="flex items-start gap-2 rounded-md bg-destructive/10 p-3 text-sm text-destructive">
                <AlertCircle className="mt-0.5 size-4 shrink-0" />
                <span>{error}</span>
              </div>
              <Button variant="outline" onClick={handleInitiate}>
                Try Again
              </Button>
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {step === "done" ? "Close" : "Cancel"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
