/** API client for Seeker OS backend. */

const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

async function fetchAPI<T>(path: string, options?: RequestInit): Promise<T> {
  const isFormData = options?.body instanceof FormData;
  const res = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: {
      // Don't set Content-Type for FormData — browser sets multipart boundary
      ...(isFormData ? {} : { "Content-Type": "application/json" }),
      ...options?.headers,
    },
  });
  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: res.statusText }));
    // FastAPI validation errors return detail as an array of {msg, ...} objects
    const detail = error.detail;
    let message: string;
    if (typeof detail === "string") {
      message = detail;
    } else if (Array.isArray(detail)) {
      message = detail.map((e: { msg?: string; message?: string } | string) =>
        typeof e === "string" ? e : e.msg || e.message || JSON.stringify(e)
      ).join("; ");
    } else if (detail && typeof detail === "object") {
      message = detail.msg || detail.message || JSON.stringify(detail);
    } else {
      message = `API error: ${res.status}`;
    }
    throw new Error(message);
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface JobSummary {
  id: number;
  title: string;
  company: string;
  score: number | null;
  status: string;
  tier_passed: number;
  comp_min: number | null;
  comp_max: number | null;
  location: string;
  workplace_type: string;
  seniority_level: string | null;
  date_posted: string;
  discovered_at: string;
  apply_url: string;
  ats_source: string | null;
  cross_ref_status: string | null;
  is_pinned: boolean;
  reject_reason: string | null;
}

export interface JobDetail extends JobSummary {
  core_title: string;
  company_homepage: string | null;
  workplace_countries: string[];
  commitment: string[];
  comp_currency: string | null;
  technical_tools: string[];
  requirements_summary: string;
  role_type: string | null;
  score_reasons: string[];
  score_gaps: string[];
  reject_details: string | null;
  jd_full: string;
  jd_fetch_status: string;
  source_id: string;
  ats_board_token: string | null;
  ats_job_id: string | null;
  discovered_query: string;
  updated_at: string;
  content_hash: string | null;
  cross_ref_date: string | null;
  cross_ref_score: number | null;
}

export interface PipelineRunSummary {
  run_id: string;
  cards_fetched: number;
  cards_new: number;
  duplicates_skipped: number;
  tier2_passed: number;
  tier2_rejected: number;
  tier3_fetched: number;
  tier3_failed: number;
  tier4_scored: number;
  tier4_rejected: number;
  tier4_hard_rejected: number;
  tier5_ready: number;
  tier5_capped: number;
  cross_ref_matches: number;
  rejection_reasons: Record<string, number>;
}

export interface PipelineProgressEvent {
  step: string;
  step_label: string;
  status: "started" | "in_progress" | "completed";
  current: number;
  total: number;
  detail: string;
  cards_fetched: number;
  cards_new: number;
  duplicates_skipped: number;
  tier2_passed: number;
  tier2_rejected: number;
  tier3_fetched: number;
  tier3_failed: number;
  tier4_scored: number;
  tier4_rejected: number;
  tier4_hard_rejected: number;
  tier5_ready: number;
}

export interface PipelineRunRecord {
  id: number;
  run_id: string;
  started_at: string;
  completed_at: string | null;
  cards_fetched: number;
  cards_new: number;
  cards_survived_tier2: number;
  jds_fetched: number;
  jobs_scored: number;
  jobs_ready: number;
  status: string;
}

export interface QuerySummary {
  id: number | null;
  source_id: string;
  slug: string;
  label: string;
  commitment: string;
  max_pages: number;
  enabled: boolean;
  last_run_at: string | null;
}

export interface FunnelStage {
  tier: number;
  label: string;
  count: number;
}

export interface FunnelStats {
  total_jobs: number;
  discovered: number;
  filtered: number;
  jd_fetched: number;
  ready: number;
  rejected: number;
  duplicate_flagged: number;
  capped: number;
  funnel: FunnelStage[];
  jd_fetch_total: number;
  jd_fetch_success: number;
  jd_fetch_failed: number;
  jd_fetch_pending: number;
  by_tier: Record<string, number>;
  by_status: Record<string, number>;
  by_ats_source: Record<string, number>;
  rejection_reasons: Record<string, number>;
  score_distribution: Record<string, number>;
}

export interface SettingsResponse {
  filters: Record<string, unknown> | null;
  scoring: Record<string, unknown> | null;
  sources: Record<string, unknown> | null;
  profile_loaded: boolean;
  profile_configured: boolean;
  queries_count: number;
}

export interface ContactInfo {
  name: string;
  email: string;
  phone: string;
  location: string;
  urls: Record<string, string>;
}

export interface MessageResponse {
  message: string;
}

export interface ProfileData {
  user: { name: string; email: string; location: string };
  contact: ContactInfo;
  location: {
    remote_only: boolean;
    accepted_cities: string[];
    accepted_states: string[];
    rejected_cities: string[];
  };
  comp: { floor: number; target: number; stretch: number };
  experience: { years: number; anchor_phrase: string };
  employment: {
    commitment: string;
    reject_commitments: string[];
    role_type: string;
    reject_role_types: string[];
  };
  blacklist: string[];
  resume: {
    master_path: string;
    accuracy_rules_path: string;
    output_dir: string;
    contact_urls: string[];
  };
  cross_reference: { repo_path: string; auto_pull: boolean };
  hard_rejects: Array<{ reason: string; pattern: string; unless_pattern?: string }>;
  instructions: string;
}

export interface FiltersData {
  filters: {
    remote_only: boolean;
    us_only: boolean;
    seniority_floor: string[];
    seniority_reject: string[];
    seniority_unknown_passes: boolean;
    seniority_title_override: string[];
    comp_floor: number;
    comp_floor_margin_pct: number;
    comp_unknown_passes: boolean;
    freshness_days: number;
    commitment_required: string;
    location_exclude: string[];
    visa_sponsorship_required: boolean;
  };
  title_filters: {
    positive: string[];
    negative: string[];
  };
}

export interface AccuracyRule {
  id: string;
  description: string;
  type: "disallowed_phrases" | "forbidden_technologies" | "required_phrases" | "experience_anchor" | "education_omission";
  severity: "high" | "medium";
  phrases?: string[] | null;
  technologies?: string[] | null;
  patterns?: string[] | null;
}

export interface AccuracyRulesData {
  rules: AccuracyRule[];
}

export interface ResumeParseResult {
  contact: ContactInfo;
  experience_years: number | null;
  current_title: string;
  key_skills: string[];
  suggested_title_positive: string[];
  suggested_comp_floor: number | null;
  summary: string;
}

export interface ResumeSummary {
  id: number;
  job_id: number;
  task: string;
  provider: string;
  model: string;
  validation_passed: boolean;
  validation_violations: Array<Record<string, unknown>>;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  generated_at: string;
  markdown_path: string;
  pdf_path: string | null;
  docx_path: string | null;
}

export interface ResumeDetail extends ResumeSummary {
  job_title: string;
  job_company: string;
  resume_text: string;
  validation_checked_at: string | null;
}

export interface ModelInfoResponse {
  id: string;
  label: string;
  provider_id: string;
  context_window: number | null;
  max_output: number | null;
  tags: string[];
  source: string;
  available: boolean;
}

export interface ProviderInfoResponse {
  id: string;
  type: string;
  label: string;
  enabled: boolean;
  auto_fetch_models: boolean;
  auth_method: string;
  oauth_token_path: string | null;
  base_url: string | null;
  api_key_set: boolean;
  models: ModelInfoResponse[];
  healthy: boolean | null;
  health_message: string;
}

export interface TierMappingResponse {
  provider: string;
  model: string;
}

export interface TaskOverrideResponse {
  tier: string;
  provider: string | null;
  model: string | null;
}

export interface ProvidersConfigResponse {
  providers: ProviderInfoResponse[];
  tiers: Record<string, TierMappingResponse>;
  tasks: Record<string, TaskOverrideResponse>;
}

export interface MasterResumeInfo {
  path: string;
  exists: boolean;
  size_bytes: number;
  format: string;
  text_preview: string;
}

// ---------------------------------------------------------------------------
// API functions
// ---------------------------------------------------------------------------

export const api = {
  // Jobs
  jobs: {
    list: (params?: { status?: string; min_score?: number; company?: string; limit?: number; offset?: number }) => {
      const search = new URLSearchParams();
      if (params?.status) search.set("status", params.status);
      if (params?.min_score) search.set("min_score", String(params.min_score));
      if (params?.company) search.set("company", params.company);
      if (params?.limit) search.set("limit", String(params.limit));
      if (params?.offset) search.set("offset", String(params.offset));
      const qs = search.toString();
      return fetchAPI<JobSummary[]>(`/api/jobs${qs ? `?${qs}` : ""}`);
    },
    get: (id: number) => fetchAPI<JobDetail>(`/api/jobs/${id}`),
    update: (id: number, data: { status?: string; notes?: string; is_pinned?: boolean }) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    reject: (id: number, reason: string, details?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason, details }),
      }),
    snooze: (id: number, days: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/snooze`, { method: "POST", body: JSON.stringify({ days }) }),
    crossRef: (id: number) => fetchAPI<Record<string, unknown>>(`/api/jobs/${id}/cross-ref`),
  },

  // Pipeline
  pipeline: {
    run: (data: { tiers?: number[]; queries?: string[]; dry_run?: boolean }) =>
      fetchAPI<PipelineRunSummary>("/api/pipeline/run", { method: "POST", body: JSON.stringify(data) }),
    runTier: (tier: number) =>
      fetchAPI<PipelineRunSummary>(`/api/pipeline/run/tier/${tier}`, { method: "POST" }),
    runs: () => fetchAPI<PipelineRunRecord[]>("/api/pipeline/runs"),
    getRun: (runId: string) => fetchAPI<PipelineRunRecord>(`/api/pipeline/runs/${runId}`),
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
    list: () => fetchAPI<QuerySummary[]>("/api/queries"),
    create: (data: { slug: string; label: string; commitment?: string; max_pages?: number; enabled?: boolean }) =>
      fetchAPI<{ message: string }>("/api/queries", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: Partial<QuerySummary>) =>
      fetchAPI<{ message: string }>(`/api/queries/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: number) =>
      fetchAPI<{ message: string }>(`/api/queries/${id}`, { method: "DELETE" }),
    run: (id: number) =>
      fetchAPI<Record<string, unknown>>(`/api/queries/${id}/run`, { method: "POST" }),
  },

  // Settings
  settings: {
    get: () => fetchAPI<SettingsResponse>("/api/settings"),
  },

  // Analytics
  analytics: {
    funnel: () => fetchAPI<FunnelStats>("/api/analytics/funnel"),
  },

  // Resumes
  resumes: {
    list: (jobId?: number) => {
      const qs = jobId ? `?job_id=${jobId}` : "";
      return fetchAPI<ResumeSummary[]>(`/api/resumes${qs}`);
    },
    get: (id: number) => fetchAPI<ResumeDetail>(`/api/resumes/${id}`),
    update: (id: number, resumeText: string) =>
      fetchAPI<MessageResponse>(`/api/resumes/${id}`, {
        method: "PUT",
        body: JSON.stringify({ resume_text: resumeText }),
      }),
    generate: (jobId: number, task?: string) =>
      fetchAPI<Record<string, unknown>>("/api/resumes/generate", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, task: task || "resume_generation_standard" }),
      }),
    validate: (id: number) =>
      fetchAPI<Record<string, unknown>>(`/api/resumes/${id}/validate`, { method: "POST" }),
    pdfUrl: (id: number) => `${API_BASE}/api/resumes/${id}/pdf`,
    markdownUrl: (id: number) => `${API_BASE}/api/resumes/${id}/markdown`,
    docxUrl: (id: number) => `${API_BASE}/api/resumes/${id}/docx`,
    getMaster: () => fetchAPI<MasterResumeInfo>("/api/resumes/master"),
    uploadMaster: (file: File) => {
      const formData = new FormData();
      formData.append("file", file);
      return fetchAPI<MasterResumeInfo>("/api/resumes/master/upload", {
        method: "POST",
        body: formData,
      });
    },
    parse: () =>
      fetchAPI<ResumeParseResult>("/api/resumes/parse", { method: "POST" }),
  },

  // Profile & Filters (editable config)
  profile: {
    get: () => fetchAPI<ProfileData>("/api/profile"),
    update: (data: Partial<ProfileData>) =>
      fetchAPI<MessageResponse>("/api/profile", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
  filters: {
    get: () => fetchAPI<FiltersData>("/api/filters"),
    update: (data: Partial<FiltersData>) =>
      fetchAPI<MessageResponse>("/api/filters", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },
  accuracyRules: {
    get: () => fetchAPI<AccuracyRulesData>("/api/accuracy-rules"),
    update: (data: AccuracyRulesData) =>
      fetchAPI<MessageResponse>("/api/accuracy-rules", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
  },

  // Models / Providers
  models: {
    getConfig: () => fetchAPI<ProvidersConfigResponse>("/api/models"),
    fetch: (providerId: string) =>
      fetchAPI<ModelInfoResponse[]>(`/api/models/fetch/${providerId}`, { method: "POST" }),
    test: (providerId: string) =>
      fetchAPI<Record<string, unknown>>(`/api/models/test/${providerId}`, { method: "POST" }),
    testAll: () =>
      fetchAPI<Record<string, unknown>[]>("/api/models/test-all", { method: "POST" }),
    updateProvider: (providerId: string, body: Record<string, unknown>) =>
      fetchAPI<ProviderInfoResponse>(`/api/models/providers/${providerId}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    updateTier: (tier: string, provider: string, model: string) =>
      fetchAPI<TierMappingResponse>(`/api/models/tiers/${tier}`, {
        method: "PUT",
        body: JSON.stringify({ provider, model }),
      }),
    updateTask: (task: string, body: { tier: string; provider?: string; model?: string }) =>
      fetchAPI<TaskOverrideResponse>(`/api/models/tasks/${task}`, {
        method: "PUT",
        body: JSON.stringify(body),
      }),
    // Anthropic OAuth flow
    oauthInitiate: () =>
      fetchAPI<{ auth_url: string; state: string }>("/api/models/anthropic/oauth/initiate", { method: "POST" }),
    oauthCallback: (code: string, state: string) =>
      fetchAPI<MessageResponse>("/api/models/anthropic/oauth/callback", {
        method: "POST",
        body: JSON.stringify({ code, state }),
      }),
    oauthStatus: () =>
      fetchAPI<{ exists: boolean; expired: boolean; expires_at: number | null; path: string }>(
        "/api/models/anthropic/oauth/status",
      ),
  },

  // Health
  health: () => fetchAPI<{ status: string }>("/api/health"),
};
