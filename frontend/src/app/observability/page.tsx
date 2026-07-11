"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Link from "next/link";
import { Activity, AlertTriangle, Coins, Loader2 } from "lucide-react";
import { api, type ObservabilityOperation, type ObservabilityOperationDetail, type ObservabilitySummary, type ObservabilityTaskSummary, type ProvidersConfigResponse } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { formatCurrency, formatDuration, formatTokens, isFreeTierOnly } from "@/lib/format";
import { DismissibleBanner } from "@/components/dismissible-banner";
import { PageHeader } from "@/components/page-header";

const TASK_LABELS: Record<string, string> = {
  jd_analysis: "JD Analysis",
  resume_generation: "Resume Generation",
  resume_generation_high_value: "Resume Generation (High Value)",
  resume_generation_standard: "Resume Generation (Standard)",
  resume_parsing: "Resume Parsing",
  resume_validation: "Resume Validation",
  company_dossier_generation: "Company Dossier",
  cover_letter_generation: "Cover Letter",
  application_answer_generation: "Application Answers",
  application_answer_critique: "Answer Critique",
  accuracy_validation: "Accuracy Validation",
  onboarding_interview: "Onboarding Interview",
  metadata_extraction: "Metadata Extraction",
  manual: "Manual",
};

const METRIC_LABELS: Record<string, string> = {
  accuracy_validation: "Accuracy Validation",
  claim_traceability: "Claim Traceability",
};

function taskLabel(task: string): string {
  return TASK_LABELS[task] ?? task;
}

function metricLabel(metric: string): string {
  return METRIC_LABELS[metric] ?? metric;
}

function money(value: number | null) {
  return value == null ? "Unavailable" : formatCurrency(value);
}

function artifactUrl(type: string, id: number): string {
  if (type === "resume") return `/resumes/${id}`;
  if (type === "job_analysis") return `/jobs/${id}`;
  if (type === "company_research") return `/jobs/${id}`;
  if (type === "job") return `/jobs/${id}`;
  return `/${type}s/${id}`;
}

function artifactLabel(type: string, id: number): string {
  if (type === "job_analysis") return `analysis #${id}`;
  if (type === "company_research") return `research #${id}`;
  return `${type} #${id}`;
}

export default function ObservabilityPage() {
  const [summary, setSummary] = useState<ObservabilitySummary | null>(null);
  const [providers, setProviders] = useState<ProvidersConfigResponse | null>(null);
  const [detail, setDetail] = useState<ObservabilityOperationDetail | null>(null);
  const [inspectingId, setInspectingId] = useState<string | null>(null);
  const [error, setError] = useState("");
  const detailRef = useRef<HTMLDivElement>(null);

  const [selectedTask, setSelectedTask] = useState<string>("resume_generation");
  const [selectedModel, setSelectedModel] = useState<string>("all");
  const [taskOps, setTaskOps] = useState<ObservabilityOperation[]>([]);
  const [taskOpsLoading, setTaskOpsLoading] = useState(false);
  const [taskOpsError, setTaskOpsError] = useState("");
  const [taskSummary, setTaskSummary] = useState<ObservabilityTaskSummary | null>(null);
  const [taskSummaryLoading, setTaskSummaryLoading] = useState(false);

  useEffect(() => {
    api.analytics.llmObservability().then(setSummary).catch((e) => setError(String(e)));
    api.models.getConfig().then(setProviders).catch(() => {});
  }, []);

  const fetchTaskData = useCallback(async (task: string, model: string) => {
    setTaskOpsLoading(true);
    setTaskOpsError("");
    setTaskSummaryLoading(true);
    try {
      const modelParam = model === "all" ? undefined : model;
      const [ops, ts] = await Promise.all([
        api.analytics.llmTaskOperations(task, modelParam),
        api.analytics.llmTaskSummary(task, modelParam),
      ]);
      setTaskOps(ops);
      setTaskSummary(ts);
    } catch (e) {
      setTaskOpsError(String(e));
      setTaskOps([]);
      setTaskSummary(null);
    } finally {
      setTaskOpsLoading(false);
      setTaskSummaryLoading(false);
    }
  }, []);

  useEffect(() => {
    setDetail(null);
    fetchTaskData(selectedTask, selectedModel);
  }, [selectedTask, selectedModel, fetchTaskData]);

  async function inspect(operationId: string) {
    setInspectingId(operationId);
    setDetail(null);
    try {
      const result = await api.analytics.llmOperation(operationId);
      setDetail(result);
      requestAnimationFrame(() => {
        detailRef.current?.scrollIntoView({ behavior: "smooth", block: "start" });
      });
    } catch (e) {
      setError(String(e));
    } finally {
      setInspectingId(null);
    }
  }

  if (error) return <div className="rounded-md border border-destructive/40 p-4 text-sm text-destructive">{error}</div>;
  if (!summary) return <div className="flex items-center gap-2 text-muted-foreground"><Loader2 className="size-4 animate-spin" />Loading observability data…</div>;

  const globalCards = [
    ["LLM calls", String(summary.total_calls), Activity],
    ["Estimated cost", money(summary.total_estimated_cost), Coins],
    ["Failed / truncated", `${summary.failed_calls} / ${summary.truncated_calls}`, AlertTriangle],
  ] as const;

  return (
    <div className="mx-auto max-w-6xl space-y-6">
      <PageHeader title="LLM Observability" description="Metadata-only cost, reliability, and quality lineage." />
      {summary.historical_data_incomplete && (
        <DismissibleBanner
          noticeId="ledger-incomplete"
          className="border-amber-500/40 bg-amber-500/10 text-amber-900 dark:text-amber-200"
        >
          Usage before ledger activation is not included.
        </DismissibleBanner>
      )}
      {isFreeTierOnly(providers?.providers ?? [], providers?.tiers ?? {}) && (
        <p className="text-xs text-muted-foreground">
          Running on free-tier models — metered cost is $0. Cost plumbing is live and will populate when a paid model is used.
        </p>
      )}
      <div className="grid gap-3 sm:grid-cols-3">
        {globalCards.map(([label, value, Icon]) => (
          <Card key={label}><CardContent className="flex items-center justify-between p-4"><div><p className="text-xs text-muted-foreground">{label}</p><p className="text-xl font-semibold">{value}</p></div><Icon className="size-5 text-muted-foreground" /></CardContent></Card>
        ))}
      </div>
      <Card>
        <CardHeader className="flex flex-row items-center justify-between gap-4">
          <CardTitle>Recent operations</CardTitle>
          <div className="flex items-end gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-muted-foreground">Task</label>
              <Select value={selectedTask} onValueChange={(v) => { if (v) { setSelectedTask(v); setSelectedModel("all"); } }}>
                <SelectTrigger className="h-8 w-48 text-xs">
                  <SelectValue>{taskLabel(selectedTask)}</SelectValue>
                </SelectTrigger>
                <SelectContent>
                  {(summary.available_tasks.length > 0 ? summary.available_tasks : ["resume_generation"]).map((t) => (
                    <SelectItem key={t} value={t} className="text-xs">{taskLabel(t)}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-xs font-semibold text-muted-foreground">Model</label>
              <Select value={selectedModel} onValueChange={(v) => v && setSelectedModel(v)}>
                <SelectTrigger className="h-8 w-48 text-xs">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem key="all" value="all" className="text-xs">All Models</SelectItem>
                  {(taskSummary?.models_used ?? []).map((m) => (
                    <SelectItem key={m} value={m} className="text-xs font-mono">{m}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardHeader>
        <CardContent className="space-y-3">
          {taskSummary && !taskSummaryLoading && (
            <div className="grid gap-2 sm:grid-cols-3 lg:grid-cols-6">
              <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Calls</p><p className="text-sm font-semibold">{taskSummary.calls}</p></div>
              <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Cost</p><p className="text-sm font-semibold">{money(taskSummary.estimated_cost)}</p></div>
              <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Failed / trunc</p><p className="text-sm font-semibold">{taskSummary.failed_calls} / {taskSummary.truncated_calls}</p></div>
              <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Avg latency</p><p className="text-sm font-semibold">{formatDuration(taskSummary.avg_latency_ms)}</p></div>
              <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Total tokens</p><p className="text-sm font-semibold">{formatTokens(taskSummary.total_tokens)}</p></div>
              <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Models</p><p className="text-sm font-semibold">{taskSummary.models_used.length > 0 ? taskSummary.models_used.length : "N/A"}</p></div>
              {taskSummary.validation_pass_rate != null && (
                <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Validation pass</p><p className="text-sm font-semibold">{taskSummary.validation_pass_rate}%</p></div>
              )}
              {taskSummary.cost_per_passing_resume != null && (
                <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Cost / passing resume</p><p className="text-sm font-semibold">{money(taskSummary.cost_per_passing_resume)}</p></div>
              )}
              {taskSummary.unsupported_claims > 0 && (
                <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Unsupported claims</p><p className="text-sm font-semibold">{taskSummary.unsupported_claims}</p></div>
              )}
              {taskSummary.overstated_claims > 0 && (
                <div className="rounded-md bg-muted/50 p-2"><p className="text-xs text-muted-foreground">Overstated claims</p><p className="text-sm font-semibold">{taskSummary.overstated_claims}</p></div>
              )}
            </div>
          )}
          {taskOpsError && <p className="text-sm text-destructive">{taskOpsError}</p>}
          {taskOpsLoading && <div className="flex items-center gap-2 text-sm text-muted-foreground"><Loader2 className="size-3.5 animate-spin" />Loading operations…</div>}
          {!taskOpsLoading && taskOps.length === 0 && <p className="text-sm text-muted-foreground">No operations found for this task.</p>}
          {!taskOpsLoading && taskOps.length > 0 && (
            <div className="max-h-80 space-y-2 overflow-y-auto">
              {taskOps.map((op) => (
                <div key={op.operation_id} className={`rounded-md border p-3 text-sm transition-colors ${detail?.operation_id === op.operation_id ? "border-primary bg-primary/5" : ""}`}>
                  <p className="font-mono text-xs">{op.operation_id}</p>
                  <p className="text-muted-foreground">
                    {new Date(op.started_at).toLocaleString()} · {op.calls} call{op.calls !== 1 ? "s" : ""} · {money(op.estimated_cost)}{!op.grouped && " · single call"}{op.model && ` · ${op.model}`}{op.total_tokens > 0 && ` · ${formatTokens(op.total_tokens)}`}{op.latency_ms > 0 && ` · ${formatDuration(op.latency_ms)}`}
                    {op.artifact_type && op.artifact_id != null && (
                      <> · <Badge variant="outline" className="text-xs"><Link href={artifactUrl(op.artifact_type, op.artifact_id)} className="text-primary hover:underline">{artifactLabel(op.artifact_type, op.artifact_id)}</Link></Badge>{op.job_title && op.company && <> for <Badge variant="outline" className="text-xs"><Link href={`/jobs/${op.job_id}`} className="text-primary hover:underline">{op.job_title}</Link></Badge> at {op.company}</>}</>
                    )}
                  </p>
                  <div className="mt-1 flex items-center gap-2">
                    {op.grouped && <Button size="sm" variant="outline" onClick={() => inspect(op.operation_id)} disabled={inspectingId === op.operation_id}>{inspectingId === op.operation_id ? <Loader2 className="size-3.5 animate-spin" /> : "Inspect"}</Button>}
                    <Badge variant={op.status === "succeeded" ? "secondary" : "destructive"}>{op.status}</Badge>
                  </div>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
      {detail && (
        <Card ref={detailRef}>
          <CardHeader><CardTitle>Operation detail</CardTitle><div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground"><span className="font-mono">{detail.operation_id}</span>{detail.artifact_type && detail.artifact_id != null && <Badge variant="outline"><Link href={artifactUrl(detail.artifact_type, detail.artifact_id)} className="text-primary hover:underline">{artifactLabel(detail.artifact_type, detail.artifact_id)}</Link></Badge>}{detail.job_title && detail.company && <>for <Badge variant="outline"><Link href={`/jobs/${detail.job_id}`} className="text-primary hover:underline">{detail.job_title}</Link></Badge> at {detail.company}</>}</div></CardHeader>
          <CardContent className="space-y-4">
            <div>
              <h3 className="mb-2 text-sm font-medium">Calls</h3>
              {detail.calls.map((call) => (
                <div key={call.call_id} className="mb-2 rounded-md bg-muted p-3 text-sm">
                  <div className="flex justify-between">
                    <span className="font-medium">{taskLabel(call.task)}</span>
                    <Badge variant="outline">{call.status}</Badge>
                  </div>
                  <p className="text-muted-foreground">{call.provider || "unrouted"} / {call.model || "unrouted"} · {formatDuration(call.latency_ms)} · {formatTokens(call.input_tokens + call.output_tokens)} tokens · {money(call.estimated_cost)}</p>
                  {(call.stop_reason || call.error_type || call.route_reason || call.prompt_name || call.temperature != null || call.max_tokens != null) && (
                    <p className="mt-1 text-xs text-muted-foreground">
                      {call.stop_reason && `stop: ${call.stop_reason}`}
                      {call.error_type && ` · ${call.error_type}`}
                      {call.route_reason && ` · route: ${call.route_reason}`}
                      {call.prompt_name && ` · ${call.prompt_name}${call.prompt_version ? `@${call.prompt_version}` : ""}`}
                      {call.temperature != null && ` · temp=${call.temperature}`}
                      {call.max_tokens != null && ` · max_tokens=${call.max_tokens}`}
                    </p>
                  )}
                </div>
              ))}
            </div>
            <div>
              <h3 className="mb-2 text-sm font-medium">Evaluations</h3>
              {(() => {
                const groups = detail.evaluations.reduce<Record<string, typeof detail.evaluations>>((acc, ev) => {
                  (acc[ev.metric_name] ??= []).push(ev);
                  return acc;
                }, {});
                return Object.entries(groups).map(([metric, evals]) => {
                  const supported = evals.filter((e) => e.label === "supported").length;
                  const flagged = evals.filter((e) => e.label !== "supported");
                  if (metric === "claim_traceability" && evals.length > 5) {
                    return (
                      <div key={metric} className="space-y-1">
                        <div className="flex items-center justify-between rounded-md border p-3 text-sm">
                          <div>
                            <span className="font-medium">{metricLabel(metric)}</span>
                            <span className="ml-2 text-xs text-muted-foreground">{evals[0].evaluator_type}{evals[0].evaluator_version && `@${evals[0].evaluator_version}`}</span>
                          </div>
                          <div className="flex items-center gap-2 text-xs text-muted-foreground">
                            <span>{evals.length} claims checked</span>
                            <Badge variant="secondary">{supported} supported</Badge>
                            {flagged.length > 0 && <Badge variant="destructive">{flagged.length} flagged</Badge>}
                          </div>
                        </div>
                        {flagged.map((evaluation) => (
                          <div key={evaluation.evaluation_id} className="flex items-center justify-between rounded-md border border-destructive/30 bg-destructive/5 p-3 text-sm">
                            <div>
                              <span className="font-medium">Flagged claim</span>
                              {evaluation.evaluator_type && <span className="ml-2 text-xs text-muted-foreground">{evaluation.evaluator_type}{evaluation.evaluator_version && `@${evaluation.evaluator_version}`}</span>}
                            </div>
                            <Badge variant="destructive">{evaluation.label}</Badge>
                          </div>
                        ))}
                      </div>
                    );
                  }
                  return evals.map((evaluation) => (
                    <div key={evaluation.evaluation_id} className="mb-2 flex items-center justify-between rounded-md border p-3 text-sm">
                      <div>
                        <span>{metricLabel(evaluation.metric_name)}</span>
                        {evaluation.evaluator_type && <span className="ml-2 text-xs text-muted-foreground">{evaluation.evaluator_type}{evaluation.evaluator_version && `@${evaluation.evaluator_version}`}</span>}
                      </div>
                      <div className="flex items-center gap-2">
                        {evaluation.score != null && <span className="text-xs text-muted-foreground">{evaluation.score.toFixed(2)}</span>}
                        <Badge variant={evaluation.passed ? "secondary" : "destructive"}>{evaluation.label || (evaluation.passed ? "passed" : "failed")}</Badge>
                      </div>
                    </div>
                  ));
                });
              })()}
            </div>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
