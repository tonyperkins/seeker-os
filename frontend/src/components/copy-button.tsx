"use client";

import { useState, useCallback } from "react";
import { Copy, Check } from "lucide-react";
import { Button } from "@/components/ui/button";

export function CopyButton({
  text,
  size = "sm",
  variant = "ghost",
  label,
}: {
  text: string;
  size?: "sm" | "default" | "lg" | "icon";
  variant?: "ghost" | "outline" | "default";
  label?: string;
}) {
  const [copied, setCopied] = useState(false);

  const handleCopy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // ignore
    }
  }, [text]);

  return (
    <Button variant={variant} size={size} onClick={handleCopy}>
      {copied ? <Check className="size-4 text-emerald-600" /> : <Copy className="size-4" />}
      {label && <span className="ml-1">{copied ? "Copied!" : label}</span>}
    </Button>
  );
}
