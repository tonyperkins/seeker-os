"use client";

import { useEffect, useState } from "react";
import { Activity, AlertTriangle, BadgeCheck, Coins, Loader2 } from "lucide-react";
import { api, type ObservabilityOperationDetail, type ObservabilitySummary } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

function money(value: number | null) {
  return value == null ? "Unavailable" : `$${value.toFixed(value < 0.01 ? 6 : 2)}`;
}

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [detail, setDetail] = useState<ObservabilityOperationDetail | null>(null);
  const [error, setError] = useState("");

  useEffect(() => {
    api.analytics.llmObservability().then(setSummary).catch((e) => setError(String(e)));
  }, []);

  async function inspect(operationId: string) {
    setDetail(null);
    try {
      setDetail(await api.analytics.llmOperation(operationId));
    } catch (e) {
      setError(String(e));
    }
  }

  if (error) return <div className="rounded-md border border-destructive/40 p-4 text-sm text-destructive">{error}</div>;
  if (!summary) return <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading observability data…</div>;

  const cards = [
    ["LLM calls", String(summary.total_calls), Activity],
    ["Estimated cost", money(summary.total_estimated_cost), Coins],
    ["Failed / truncated", `${summary.failed_calls} / ${summary.truncated_calls}`, AlertTriangle],
    ["Validation pass rate", summary.validation_pass_rate == null ? "No data" : `${summary.validation_pass_rate}%`, BadgeCheck],
  ] as const;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">LLM Observability</h1>
        <p className="text-sm text-muted-foreground">Metadata-only cost, reliability, and quality lineage.</p>
      </div>
      {summary.historical_data_incomplete && (
        <div className="rounded-md border border-amber-500/40 bg-amber-500/10 p-3 text-sm">Usage before ledger activation is not included.</div>
      )}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        {cards.map(([label, value, Icon]) => (
          <Card key={label}><CardContent className="flex items-center justify-between p-4"><div><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value}</p></div><Icon className="size-5 text-muted-foreground" /></CardContent></Card>
        ))}
      </div>
      <div className="grid gap-3 sm:grid-cols-3">
        <Card><CardHeader><CardTitle className="text-sm">Unsupported claims</CardTitle></CardHeader><CardContent className="text-2xl font-semibold">{summary.unsupported_claims}</CardContent></Card>
        <Card><CardHeader><CardTitle className="text-sm">Overstated claims</CardTitle></CardHeader><CardContent className="text-2xl font-semibold">{summary.overstated_claims}</CardContent></Card>
        <Card><CardHeader><CardTitle className="text-sm">Cost per passing resume</CardTitle></CardHeader><CardContent className="text-2xl font-semibold">{money(summary.cost_per_passing_resume)}</CardContent></Card>
      </div>
      <Card>
        <CardHeader><CardTitle>Recent resume operations</CardTitle></CardHeader>
        <CardContent className="space-y-2">
          {summary.recent_operations.length === 0 && <p className="text-sm text-muted-foreground">No correlated resume operations yet.</p>}
          {summary.recent_operations.map((op) => (
            <div key={op.operation_id} className="flex flex-wrap items-center justify-between gap-3 rounded-md border p-3 text-sm">
              <div><p className="font-mono text-xs">{op.operation_id}</p><p className="text-muted-foreground">{new Date(op.started_at).toLocaleString()} · {op.calls} calls · {money(op.estimated_cost)}</p></div>
              <div className="flex items-center gap-2"><Badge variant={op.status === "succeeded" ? "secondary" : "destructive"}>{op.status}</Badge><Button size="sm" variant="outline" onClick={() => inspect(op.operation_id)}>Inspect</Button></div>
            </div>
          ))}
        </CardContent>
      </Card>
      {detail && (
        <Card>
          <CardHeader><CardTitle>Operation detail</CardTitle></CardHeader>
          <CardContent className="space-y-4">
            <div><h3 className="mb-2 text-sm font-medium">Calls</h3>{detail.calls.map((call) => <div key={call.call_id} className="mb-2 rounded-md bg-muted p-3 text-sm"><div className="flex justify-between"><span className="font-medium">{call.task}</span><Badge variant="outline">{call.status}</Badge></div><p className="text-muted-foreground">{call.provider || "unrouted"} / {call.model || "unrouted"} · {call.latency_ms}ms · {call.input_tokens + call.output_tokens} tokens · {money(call.estimated_cost)}</p></div>)}</div>
            <div><h3 className="mb-2 text-sm font-medium">Evaluations</h3>{detail.evaluations.map((evaluation) => <div key={evaluation.evaluation_id} className="mb-2 flex items-center justify-between rounded-md border p-3 text-sm"><span>{evaluation.metric_name}</span><Badge variant={evaluation.passed ? "secondary" : "destructive"}>{evaluation.label || (evaluation.passed ? "passed" : "failed")}</Badge></div>)}</div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
