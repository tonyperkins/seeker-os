"use client";

import { useState } from "react";
import { Shield } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { api } from "@/lib/api";

const POLICY_LABELS: Record<string, string> = {
  allowed: "AI Allowed",
  draft_only: "Draft Only",
  forbidden: "AI Forbidden",
};

export function AIPolicyToggle({
  jobId,
  initialPolicy,
}: {
  jobId: number;
  initialPolicy: string | null;
}) {
  const [policy, setPolicy] = useState<string | null>(initialPolicy);
  const [saving, setSaving] = useState(false);

  const handleChange = async (value: string | null) => {
    setSaving(true);
    try {
      const policyValue = value === "default" ? null : value;
      await api.jobs.update(jobId, { ai_policy: policyValue ?? "" });
      setPolicy(policyValue);
    } catch (err) {
      console.error("Failed to update AI policy:", err);
    } finally {
      setSaving(false);
    }
  };

  const displayValue = policy ?? "default";

  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Shield className="size-4 text-muted-foreground" />
        <span className="text-sm font-medium">AI Generation Policy</span>
        {policy && (
          <Badge variant={policy === "forbidden" ? "destructive" : "secondary"}>
            {POLICY_LABELS[policy] ?? policy}
          </Badge>
        )}
        {!policy && (
          <Badge variant="outline">Channel default</Badge>
        )}
      </div>
      <Select value={displayValue} onValueChange={handleChange} disabled={saving}>
        <SelectTrigger className="w-full">
          <SelectValue placeholder="Channel default" />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="default">Channel default</SelectItem>
          <SelectItem value="allowed">AI Allowed</SelectItem>
          <SelectItem value="draft_only">Draft Only</SelectItem>
          <SelectItem value="forbidden">AI Forbidden</SelectItem>
        </SelectContent>
      </Select>
      <p className="text-xs text-muted-foreground">
        Controls whether AI can generate content for this job.
        When set to forbidden, AI authoring is refused for this posting.
      </p>
    </div>
  );
}
