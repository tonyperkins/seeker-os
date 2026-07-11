/** API client for Seeker OS backend — barrel re-export from split modules. */

import { trackActivity } from "@/lib/activity-store";
import { fetchAPI, API_BASE } from "@/lib/api-core";
import type * as T from "@/lib/api-types";

// Re-export all types
export type {
  ApplicationEvent,
  JobSummary,
  JobSortKey,
  SortOrder,
  PaginatedJobsResponse,
  RecruiterContact,
  JobDetail,
  JobCreateRequest,
  JobCreateResponse,
  RefilterRescoreResult,
  PipelineRunSummary,
  PipelineProgressEvent,
  ResumeProgressEvent,
  PipelineRunRecord,
  QuerySummary,
  FunnelStage,
  FunnelStats,
  MovementEvent,
  MovementReport,
  AgingBucket,
  AgingReport,
  VerdictDistribution,
  SignalQualityReport,
  SpendByTask,
  SpendByModel,
  PricingRouteComparison,
  SpendReport,
  ObservabilityOperation,
  ObservabilitySummary,
  ObservabilityCall,
  ObservabilityEvaluation,
  ObservabilityOperationDetail,
  SkipReasonOption,
  NoReasonSkip,
  SettingsResponse,
  ContactInfo,
  MessageResponse,
  RestoreResult,
  ProfileData,
  FiltersData,
  AccuracyRule,
  AccuracyRulesData,
  ResumeParseResult,
  ResumeSummary,
  ResumeDetail,
  ModelInfoResponse,
  ProviderInfoResponse,
  TierMappingResponse,
  TaskOverrideResponse,
  ProvidersConfigResponse,
  MasterResumeInfo,
  WikipediaInfo,
  SourceRef,
  LayoffEvent,
  LastRound,
  FundingDossier,
  SentimentTheme,
  SentimentDossier,
  FitDossier,
  VerdictFlags,
  RetrievalSnippetData,
  CompanyResearchResult,
  ResearchBreakdownItem,
  RetrievalSettings,
  RetrievalSettingsUpdate,
  TestConnectionResult,
  NamedGap,
  HardBlocker,
  RubricDimension,
  CompAssessment,
  PositioningAssessment,
  CompanyFitAssessment,
  TailoringGuidance,
  JobAnalysisResult,
} from "@/lib/api-types";

export const api = {
  // Demo mode
  demoMode: {
    get: () => fetchAPI<{ demo_mode: boolean }>("/api/demo-mode"),
  },

  // Jobs
  jobs: {
    list: (
      params?: { status?: string; min_score?: number; min_tier?: number; company?: string; search?: string; source?: string; run_id?: string; verdict?: string; exclude_status?: string; sort_by?: T.JobSortKey; order?: T.SortOrder; limit?: number; offset?: number },
      options?: { signal?: AbortSignal },
    ) => {
      const search = new URLSearchParams();
      if (params?.status) search.set("status", params.status);
      if (params?.min_tier) search.set("min_tier", String(params.min_tier));
      if (params?.min_score) search.set("min_score", String(params.min_score));
      if (params?.company) search.set("company", params.company);
      if (params?.search) search.set("search", params.search);
      if (params?.source) search.set("source", params.source);
      if (params?.run_id) search.set("run_id", params.run_id);
      if (params?.verdict) search.set("verdict", params.verdict);
      if (params?.exclude_status) search.set("exclude_status", params.exclude_status);
      if (params?.sort_by) search.set("sort_by", params.sort_by);
      if (params?.order) search.set("order", params.order);
      if (params?.limit) search.set("limit", String(params.limit));
      if (params?.offset) search.set("offset", String(params.offset));
      const qs = search.toString();
      return fetchAPI<T.PaginatedJobsResponse>(`/api/jobs${qs ? `?${qs}` : ""}`, options);
    },
    get: (id: number) => fetchAPI<T.JobDetail>(`/api/jobs/${id}`),
    create: (data: T.JobCreateRequest) =>
      fetchAPI<T.JobCreateResponse>(`/api/jobs`, { method: "POST", body: JSON.stringify(data) }),
    override: (id: number, note?: string, targetStatus?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/override`, {
        method: "POST",
        body: JSON.stringify({ note, target_status: targetStatus || "ready" }),
      }),
    update: (id: number, data: {
      status?: string;
      notes?: string;
      is_pinned?: boolean;
      ai_policy?: string;
      title?: string;
      company?: string;
      location?: string;
      workplace_type?: string;
      seniority_level?: string;
      role_type?: string;
      comp_min?: number;
      comp_max?: number;
      comp_currency?: string;
      company_homepage?: string;
      apply_url?: string;
      jd_full?: string;
    }) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    reject: (id: number, reason: string, details?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason, details }),
      }),
    skip: (id: number, reason?: string, details?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/skip`, {
        method: "POST",
        body: JSON.stringify({ reason, details }),
      }),
    apply: (id: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/apply`, { method: "POST" }),
    delete: (id: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}`, { method: "DELETE" }),
    addRecruiter: (jobId: number, data: {
      name?: string; email?: string; phone?: string; linkedin?: string;
      agency?: string; source?: string; contacted_at?: string; notes?: string;
    }) =>
      fetchAPI<T.RecruiterContact>(`/api/jobs/${jobId}/recruiters`, {
        method: "POST", body: JSON.stringify(data),
      }),
    updateRecruiterEntity: (recruiterId: number, data: {
      name?: string; email?: string; phone?: string; linkedin?: string; agency?: string;
    }) =>
      fetchAPI<T.RecruiterContact>(`/api/jobs/recruiters/${recruiterId}`, {
        method: "PATCH", body: JSON.stringify(data),
      }),
    updateRecruiterAssociation: (associationId: number, data: {
      source?: string; notes?: string;
    }) =>
      fetchAPI<T.RecruiterContact>(`/api/jobs/recruiters/association/${associationId}`, {
        method: "PATCH", body: JSON.stringify(data),
      }),
    deleteRecruiter: (associationId: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/recruiters/association/${associationId}`, {
        method: "DELETE",
      }),
    transition: (id: number, targetStatus: string, opts?: { occurred_at?: string; note?: string; metadata?: Record<string, unknown> }) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ target_status: targetStatus, ...opts }),
      }),
    logEngagedEvent: (id: number, eventType: string, opts?: { occurred_at?: string; note?: string; metadata?: Record<string, unknown> }) =>
      fetchAPI<T.ApplicationEvent>(`/api/jobs/${id}/engaged-events`, {
        method: "POST",
        body: JSON.stringify({ event_type: eventType, ...opts }),
      }),
    cleanStart: (id: number, targetStatus: string, opts?: { occurred_at?: string; applied_occurred_at?: string; note?: string; metadata?: Record<string, unknown> }) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/clean-start`, {
        method: "POST",
        body: JSON.stringify({ target_status: targetStatus, ...opts }),
      }),
    crossRef: (id: number) => fetchAPI<Record<string, unknown>>(`/api/jobs/${id}/cross-ref`),
    companyResearch: {
      get: (id: number) => fetchAPI<T.CompanyResearchResult>(`/api/jobs/${id}/company-research`),
      run: (id: number, forceRefresh?: boolean) =>
        trackActivity("research", `Researching job #${id}`, fetchAPI<T.CompanyResearchResult>(`/api/jobs/${id}/company-research?force_refresh=${forceRefresh ?? false}`, { method: "POST" })) as Promise<T.CompanyResearchResult>,
    },
    analysis: {
      get: (id: number) => fetchAPI<T.JobAnalysisResult>(`/api/jobs/${id}/analysis`),
      run: (id: number) =>
        trackActivity("analysis", `Analyzing job #${id}`, fetchAPI<T.JobAnalysisResult>(`/api/jobs/${id}/analysis`, { method: "POST" })) as Promise<T.JobAnalysisResult>,
    },
    refilterRescore: (data: { job_ids?: number[]; run_id?: string }) =>
      trackActivity("refilter", `Refilter & rescore ${data.job_ids?.length ?? 0} jobs`, fetchAPI<T.RefilterRescoreResult[]>(`/api/jobs/refilter-rescore`, { method: "POST", body: JSON.stringify(data) })) as Promise<T.RefilterRescoreResult[]>,
    listNoReasonSkips: () =>
      fetchAPI<T.NoReasonSkip[]>("/api/jobs/skipped/no-reason"),
    annotateSkip: (id: number, reason: string, details?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/annotate-skip`, {
        method: "POST",
        body: JSON.stringify({ reason, details }),
      }),
  },

  // Pipeline
  pipeline: {
    run: (data: { tiers?: number[]; queries?: string[]; dry_run?: boolean }) =>
      fetchAPI<T.PipelineRunSummary>("/api/pipeline/run", { method: "POST", body: JSON.stringify(data) }),
    runTier: (tier: number) =>
      fetchAPI<T.PipelineRunSummary>(`/api/pipeline/run/tier/${tier}`, { method: "POST" }),
    runs: () => fetchAPI<T.PipelineRunRecord[]>("/api/pipeline/runs"),
    getRun: (runId: string) => fetchAPI<T.PipelineRunRecord>(`/api/pipeline/runs/${runId}`),
    runStream: (data: { tiers?: number[]; queries?: string[]; dry_run?: boolean }) => {
      const controller = new AbortController();
      const response = fetch(`${API_BASE}/api/pipeline/run/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(data),
        signal: controller.signal,
      });
      return { response, controller };
    },
  },

  // Queries
  queries: {
    list: () => fetchAPI<T.QuerySummary[]>("/api/queries"),
    create: (data: { slug: string; label: string; commitment?: string; max_pages?: number; enabled?: boolean; search_query?: string }) =>
      fetchAPI<{ message: string }>("/api/queries", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: Partial<T.QuerySummary>) =>
      fetchAPI<{ message: string }>(`/api/queries/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: number) =>
      fetchAPI<{ message: string }>(`/api/queries/${id}`, { method: "DELETE" }),
    run: (id: number, forceFullPull?: boolean) =>
      trackActivity("pipeline", `Running query #${id}${forceFullPull ? " (full pull)" : ""}`, fetchAPI<Record<string, unknown>>(`/api/queries/${id}/run${forceFullPull ? "?force_full_pull=true" : ""}`, { method: "POST" })) as Promise<Record<string, unknown>>,
  },

  // Settings
  settings: {
    get: () => fetchAPI<T.SettingsResponse>("/api/settings"),
    reload: () =>
      fetchAPI<T.MessageResponse>("/api/settings/reload", { method: "POST" }),
  },

  // Analytics
  analytics: {
    funnel: () => fetchAPI<T.FunnelStats>("/api/analytics/funnel"),
    movement: (params?: { days?: number; limit?: number }) => {
      const search = new URLSearchParams();
      if (params?.days) search.set("days", String(params.days));
      if (params?.limit) search.set("limit", String(params.limit));
      const qs = search.toString();
      return fetchAPI<T.MovementReport>(`/api/analytics/movement${qs ? `?${qs}` : ""}`);
    },
    aging: () => fetchAPI<T.AgingReport>("/api/analytics/aging"),
    signalQuality: () => fetchAPI<T.SignalQualityReport>("/api/analytics/signal-quality"),
    spend: () => fetchAPI<T.SpendReport>("/api/analytics/spend"),
    llmObservability: () => fetchAPI<T.ObservabilitySummary>("/api/analytics/llm-observability"),
    llmOperation: (operationId: string) =>
      fetchAPI<T.ObservabilityOperationDetail>(`/api/analytics/llm-observability/operations/${operationId}`),
  },

  // Resumes
  resumes: {
    list: (params?: { jobId?: number; search?: string; sort_by?: string; order?: "asc" | "desc" }) => {
      const qs = new URLSearchParams();
      if (params?.jobId) qs.set("job_id", String(params.jobId));
      if (params?.search) qs.set("search", params.search);
      if (params?.sort_by) qs.set("sort_by", params.sort_by);
      if (params?.order) qs.set("order", params.order);
      const q = qs.toString();
      return fetchAPI<T.ResumeSummary[]>(`/api/resumes${q ? `?${q}` : ""}`);
    },
    pendingCount: () => fetchAPI<{ count: number }>("/api/resumes/pending-count"),
    get: (id: number) => fetchAPI<T.ResumeDetail>(`/api/resumes/${id}`),
    update: (id: number, resumeText: string) =>
      fetchAPI<T.MessageResponse>(`/api/resumes/${id}`, {
        method: "PUT",
        body: JSON.stringify({ resume_text: resumeText }),
      }),
    delete: (id: number) =>
      fetchAPI<T.MessageResponse>(`/api/resumes/${id}`, { method: "DELETE" }),
    generate: (jobId: number, task?: string) =>
      trackActivity("resume", `Generating resume for job #${jobId}`, fetchAPI<Record<string, unknown>>("/api/resumes/generate", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, task: task || "resume_generation_standard" }),
      })) as Promise<Record<string, unknown>>,
    createManual: (jobId: number, resumeText: string) =>
      fetchAPI<{ resume_id: number; validation_passed: boolean }>("/api/resumes/manual", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, resume_text: resumeText }),
      }),
    generateStream: (jobId: number, task?: string) => {
      const controller = new AbortController();
      const response = fetch(`${API_BASE}/api/resumes/generate/stream`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ job_id: jobId, task: task || "resume_generation_standard" }),
        signal: controller.signal,
      });
      return { response, controller };
    },
    validate: (id: number) =>
      fetchAPI<Record<string, unknown>>(`/api/resumes/${id}/validate`, { method: "POST" }),
    clearExports: (id: number) =>
      fetchAPI<T.MessageResponse>(`/api/resumes/${id}/exports`, { method: "DELETE" }),
    pdfUrl: (id: number) => `/api/resumes/${id}/pdf`,
    markdownUrl: (id: number) => `/api/resumes/${id}/markdown`,
    docxUrl: (id: number) => `/api/resumes/${id}/docx`,
    getMaster: () => fetchAPI<T.MasterResumeInfo>("/api/resumes/master"),
    getMasterContent: () => fetchAPI<{ content: string }>("/api/resumes/master/content"),
    updateMasterContent: (content: string) =>
      fetchAPI<{ message: string }>("/api/resumes/master/content", {
        method: "PUT",
        body: JSON.stringify({ content }),
      }),
    uploadMaster: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return fetchAPI<T.MasterResumeInfo>("/api/resumes/master/upload", {
        method: "POST",
        body: formData,
      });
    },
    parse: () =>
      fetchAPI<T.ResumeParseResult>("/api/resumes/parse", { method: "POST" }),
  },

  // Profile & Filters (editable config)
  profile: {
    get: () => fetchAPI<T.ProfileData>("/api/profile"),
    update: (data: Partial<T.ProfileData>) =>
      fetchAPI<T.MessageResponse>("/api/profile", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
  filters: {
    get: () => fetchAPI<T.FiltersData>("/api/filters"),
    update: (data: Partial<T.FiltersData>) =>
      fetchAPI<T.MessageResponse>("/api/filters", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
  accuracyRules: {
    get: () => fetchAPI<T.AccuracyRulesData>("/api/accuracy-rules"),
    update: (data: T.AccuracyRulesData) =>
      fetchAPI<T.MessageResponse>("/api/accuracy-rules", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    aiGenerate: (description: string) =>
      fetchAPI<T.AccuracyRulesData>("/api/accuracy-rules/ai-generate", {
        method: "POST",
        body: JSON.stringify({ description }),
      }),
  },

  // Models / Providers
  models: {
    getConfig: () => fetchAPI<T.ProvidersConfigResponse>("/api/models"),
    fetch: (providerId: string) =>
      fetchAPI<T.ModelInfoResponse[]>(`/api/models/fetch/${providerId}`, { method: "POST" }),
    test: (providerId: string) =>
      fetchAPI<Record<string, unknown>>(`/api/models/test/${providerId}`, { method: "POST" }),
    testAll: () =>
      fetchAPI<Record<string, unknown>[]>("/api/models/test-all", { method: "POST" }),
    updateProvider: (providerId: string, body: Record<string, unknown>) =>
      fetchAPI<T.ProviderInfoResponse>(`/api/models/providers/${providerId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    updateTier: (tier: string, provider: string, model: string) =>
      fetchAPI<T.TierMappingResponse>(`/api/models/tiers/${tier}`, {
        method: "PUT",
        body: JSON.stringify({ provider, model }),
      }),
    updateTask: (task: string, body: { tier: string; provider?: string; model?: string }) =>
      fetchAPI<T.TaskOverrideResponse>(`/api/models/tasks/${task}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    updateModelPricing: (
      providerId: string,
      modelId: string,
      inputPricePerMtok: number | null,
      outputPricePerMtok: number | null,
    ) =>
      fetchAPI<Record<string, unknown>>(
        `/api/models/${providerId}/models/${modelId}/pricing`,
        {
          method: "PUT",
          body: JSON.stringify({
            input_price_per_mtok: inputPricePerMtok,
            output_price_per_mtok: outputPricePerMtok,
          }),
        },
      ),
    resetModelPricing: (providerId: string, modelId: string) =>
      fetchAPI<Record<string, unknown>>(
        `/api/models/${providerId}/models/${modelId}/pricing`,
        { method: "DELETE" },
      ),
  },

  // Health
  health: () => fetchAPI<{ status: string }>("/api/health"),

  // Logs
  logs: (tail?: number) =>
    fetchAPI<{ lines: string[]; path: string }>(`/api/logs${tail ? `?tail=${tail}` : ""}`),

  // Company Research Settings
  companyResearchSettings: {
    get: () => fetchAPI<T.RetrievalSettings>("/api/settings/company-research"),
    update: (data: T.RetrievalSettingsUpdate) =>
      fetchAPI<T.MessageResponse>("/api/settings/company-research", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    testConnection: () =>
      fetchAPI<T.TestConnectionResult>("/api/settings/company-research/test-connection", {
        method: "POST",
      }),
  },

  // Backup / Restore
  backup: {
    download: async (): Promise<Blob> => {
      const res = await fetch(`${API_BASE}/api/backup`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `API error: ${res.status}`);
      }
      return res.blob();
    },
    restore: async (file: File): Promise<T.RestoreResult> => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/api/backup/restore`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `API error: ${res.status}`);
      }
      return res.json();
    },
    downloadDB: async (): Promise<Blob> => {
      const res = await fetch(`${API_BASE}/api/backup/db`);
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `API error: ${res.status}`);
      }
      return res.blob();
    },
    restoreDB: async (file: File): Promise<T.MessageResponse> => {
      const formData = new FormData();
      formData.append("file", file);
      const res = await fetch(`${API_BASE}/api/backup/db/restore`, {
        method: "POST",
        body: formData,
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({ detail: res.statusText }));
        throw new Error(err.detail || `API error: ${res.status}`);
      }
      return res.json();
    },
  },
};
