/** API client for Seeker OS backend. */

// Server-side renders (SSR) run inside the container — use the Docker service name.
// Client-side fetches use relative URLs so they work behind any reverse proxy
// (Next.js rewrites /api/* to the backend).
const API_BASE =
  typeof window === "undefined"
    ? process.env["SERVER_API_URL"] || process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000"
    : "";

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

export interface ApplicationEvent {
  id: number;
  job_id: number;
  event_type: string;
  actor: string;
  occurred_at: string;
  created_at: string;
  metadata: Record<string, unknown> | null;
  note: string | null;
}

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
  reject_details: string | null;
  ai_policy: string | null;
  source_id: string;
  discovered_query: string;
  run_id: string | null;
  is_stale: boolean;
  days_since_last_activity: number | null;
  has_analysis: boolean;
  has_research: boolean;
  has_resume: boolean;
  analysis_verdict: string | null;
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
  ai_policy: string | null;
  research_adjusted_score: number | null;
  research_delta: number;
  analysis_verdict: string | null;
  analysis_delta: number;
  net_score: number | null;
  filter_warnings: string[];
  overridden_at: string | null;
  override_note: string | null;
  original_reject_reason: string | null;
  is_stale: boolean;
  days_since_last_activity: number | null;
  events: ApplicationEvent[];
}

export interface JobCreateRequest {
  url: string;
  title?: string;
  company?: string;
  location?: string;
  workplace_type?: string;
  seniority_level?: string;
  comp_min?: number;
  comp_max?: number;
  comp_currency?: string;
  company_homepage?: string;
  jd_text?: string;
  force?: boolean;
}

export interface JobCreateResponse {
  status: "created" | "already_exists" | "fetch_failed" | "possible_duplicate" | "likely_duplicate";
  job: JobDetail | null;
  existing_job_id: number | null;
  existing_summary: string | null;
  fetch_error: string | null;
  filter_warnings: string[];
}

export interface RefilterRescoreResult {
  job_id: number;
  status: string;
  score: number | null;
  net_score: number | null;
  previous_score: number | null;
  previous_status: string | null;
  score_changed: boolean;
  status_changed: boolean;
  filter_passed: boolean;
  filter_reason: string | null;
  research_applied: boolean;
  analysis_verdict: string | null;
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

export interface ResumeProgressEvent {
  step: string;
  step_label: string;
  status: "started" | "in_progress" | "completed";
  detail: string;
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
  search_query: string | null;
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

export interface RestoreResult {
  message: string;
  restored: string[];
  skipped: string[];
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
  // Demo mode
  demoMode: {
    get: () => fetchAPI<{ demo_mode: boolean }>("/api/demo-mode"),
  },

  // Jobs
  jobs: {
    list: (params?: { status?: string; min_score?: number; min_tier?: number; company?: string; search?: string; source?: string; run_id?: string; verdict?: string; exclude_status?: string; limit?: number; offset?: number }) => {
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
      if (params?.limit) search.set("limit", String(params.limit));
      if (params?.offset) search.set("offset", String(params.offset));
      const qs = search.toString();
      return fetchAPI<{ jobs: JobSummary[]; total: number }>(`/api/jobs${qs ? `?${qs}` : ""}`);
    },
    get: (id: number) => fetchAPI<JobDetail>(`/api/jobs/${id}`),
    create: (data: JobCreateRequest) =>
      fetchAPI<JobCreateResponse>(`/api/jobs`, { method: "POST", body: JSON.stringify(data) }),
    override: (id: number, note?: string, targetStatus?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/override`, {
        method: "POST",
        body: JSON.stringify({ note, target_status: targetStatus || "ready" }),
      }),
    update: (id: number, data: { status?: string; notes?: string; is_pinned?: boolean; ai_policy?: string }) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    reject: (id: number, reason: string, details?: string) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/reject`, {
        method: "POST",
        body: JSON.stringify({ reason, details }),
      }),
    skip: (id: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/skip`, { method: "POST" }),
    apply: (id: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/apply`, { method: "POST" }),
    delete: (id: number) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}`, { method: "DELETE" }),
    transition: (id: number, targetStatus: string, opts?: { occurred_at?: string; note?: string; metadata?: Record<string, unknown> }) =>
      fetchAPI<{ message: string }>(`/api/jobs/${id}/transition`, {
        method: "POST",
        body: JSON.stringify({ target_status: targetStatus, ...opts }),
      }),
    logEngagedEvent: (id: number, eventType: string, opts?: { occurred_at?: string; note?: string; metadata?: Record<string, unknown> }) =>
      fetchAPI<ApplicationEvent>(`/api/jobs/${id}/engaged-events`, {
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
      get: (id: number) => fetchAPI<CompanyResearchResult>(`/api/jobs/${id}/company-research`),
      run: (id: number, forceRefresh?: boolean) =>
        fetchAPI<CompanyResearchResult>(`/api/jobs/${id}/company-research?force_refresh=${forceRefresh ?? false}`, { method: "POST" }),
    },
    analysis: {
      get: (id: number) => fetchAPI<JobAnalysisResult>(`/api/jobs/${id}/analysis`),
      run: (id: number) => fetchAPI<JobAnalysisResult>(`/api/jobs/${id}/analysis`, { method: "POST" }),
    },
    refilterRescore: (data: { job_ids?: number[]; run_id?: string }) =>
      fetchAPI<RefilterRescoreResult[]>(`/api/jobs/refilter-rescore`, { method: "POST", body: JSON.stringify(data) }),
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
    create: (data: { slug: string; label: string; commitment?: string; max_pages?: number; enabled?: boolean; search_query?: string }) =>
      fetchAPI<{ message: string }>("/api/queries", { method: "POST", body: JSON.stringify(data) }),
    update: (id: number, data: Partial<QuerySummary>) =>
      fetchAPI<{ message: string }>(`/api/queries/${id}`, { method: "PATCH", body: JSON.stringify(data) }),
    delete: (id: number) =>
      fetchAPI<{ message: string }>(`/api/queries/${id}`, { method: "DELETE" }),
    run: (id: number, forceFullPull?: boolean) =>
      fetchAPI<Record<string, unknown>>(`/api/queries/${id}/run${forceFullPull ? "?force_full_pull=true" : ""}`, { method: "POST" }),
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
    delete: (id: number) =>
      fetchAPI<MessageResponse>(`/api/resumes/${id}`, { method: "DELETE" }),
    generate: (jobId: number, task?: string) =>
      fetchAPI<Record<string, unknown>>("/api/resumes/generate", {
        method: "POST",
        body: JSON.stringify({ job_id: jobId, task: task || "resume_generation_standard" }),
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
      fetchAPI<MessageResponse>(`/api/resumes/${id}/exports`, { method: "DELETE" }),
    pdfUrl: (id: number) => `/api/resumes/${id}/pdf`,
    markdownUrl: (id: number) => `/api/resumes/${id}/markdown`,
    docxUrl: (id: number) => `/api/resumes/${id}/docx`,
    getMaster: () => fetchAPI<MasterResumeInfo>("/api/resumes/master"),
    getMasterContent: () => fetchAPI<{ content: string }>("/api/resumes/master/content"),
    updateMasterContent: (content: string) =>
      fetchAPI<{ message: string }>("/api/resumes/master/content", {
        method: "PUT",
        body: JSON.stringify({ content }),
      }),
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
    aiGenerate: (description: string) =>
      fetchAPI<AccuracyRulesData>("/api/accuracy-rules/ai-generate", {
        method: "POST",
        body: JSON.stringify({ description }),
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

  // Logs
  logs: (tail?: number) =>
    fetchAPI<{ lines: string[]; path: string }>(`/api/logs${tail ? `?tail=${tail}` : ""}`),

  // Company Research Settings
  companyResearchSettings: {
    get: () => fetchAPI<RetrievalSettings>("/api/settings/company-research"),
    update: (data: RetrievalSettingsUpdate) =>
      fetchAPI<MessageResponse>("/api/settings/company-research", {
        method: "PUT",
        body: JSON.stringify(data),
      }),
    testConnection: () =>
      fetchAPI<TestConnectionResult>("/api/settings/company-research/test-connection", {
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
    restore: async (file: File): Promise<RestoreResult> => {
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
    restoreDB: async (file: File): Promise<MessageResponse> => {
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

// ---------------------------------------------------------------------------
// Company Research types
// ---------------------------------------------------------------------------

export interface WikipediaInfo {
  title: string;
  description: string;
  extract: string;
  url: string | null;
  thumbnail: string | null;
}

export interface SourceRef {
  url: string;
  retrieved: string;
}

export interface LayoffEvent {
  date: string | null;
  pct: number | null;
  count: number | null;
  source: string | null;
}

export interface LastRound {
  type: string | null;
  amount_usd: number | null;
  date: string | null;
  lead_investors: string[];
}

export interface FundingDossier {
  founded: number | null;
  hq: string | null;
  public: boolean;
  stage: string | null;
  total_raised_usd: number | null;
  valuation_usd: number | null;
  last_round: LastRound | null;
  headcount: number | null;
  headcount_trend: string | null;
  layoffs: LayoffEvent[];
  financial_health: string | null;
  confidence: number;
  sources: SourceRef[];
  stripped_count: number;
}

export interface SentimentTheme {
  theme: string;
  frequency: string;
  paraphrase: string;
  source: string;
  age_months: number | null;
}

export interface SentimentDossier {
  overall_rating_estimate: number | null;
  rating_scale: string;
  ceo_approval_pct: number | null;
  recommend_pct: number | null;
  positives: SentimentTheme[];
  negatives: SentimentTheme[];
  staleness_warning: string | null;
  confidence: number;
  sources: SourceRef[];
  stripped_count: number;
}

export interface FitDossier {
  remote_policy: string | null;
  remote_walkback: string | null;
  size_bucket: string | null;
  ic_vs_mgmt_culture: string | null;
  comp_band: string | null;
  clearance_required: boolean;
  confidence: number;
  sources: SourceRef[];
  stripped_count: number;
}

export interface VerdictFlags {
  green: string[];
  red: string[];
  watch: string[];
}

export interface RetrievalSnippetData {
  url: string;
  title: string;
  snippet: string;
  source_domain: string;
  score: number | null;
}

export interface CompanyResearchResult {
  id: number | null;
  job_id: number;
  company_name: string;
  company_homepage: string | null;
  wikipedia: WikipediaInfo | null;
  overall_confidence: number;
  summary: string;
  verdict_flags: VerdictFlags;
  funding: FundingDossier | null;
  sentiment: SentimentDossier | null;
  fit: FitDossier | null;
  gaps: string[];
  sources_used: string[];
  errors: string[];
  researched_at: string;
  verification_state: "verified" | "unverified" | "mismatch";
  retrieval_used: boolean;
  retrieval_sources: SourceRef[];
  retrieval_snippets: RetrievalSnippetData[];
  research_adjusted_score: number | null;
  research_delta: number;
  research_breakdown: ResearchBreakdownItem[];
  research_adjustment_applied: boolean;
}

export interface ResearchBreakdownItem {
  factor: string;
  delta: number;
  confidence: number;
  source_section: string;
}

// ---------------------------------------------------------------------------
// Company Research Settings types
// ---------------------------------------------------------------------------

export interface RetrievalSettings {
  provider_type: string;
  api_key_configured: boolean;
  max_results: number;
  timeout_seconds: number;
  funding_query_template: string;
  sentiment_query_template: string;
  confidence_floor: number;
  staleness_months: number;
  source_trust_order: string[];
  user_agent: string;
}

export interface RetrievalSettingsUpdate {
  provider_type?: string;
  api_key?: string;
  max_results?: number;
  timeout_seconds?: number;
  funding_query_template?: string;
  sentiment_query_template?: string;
  confidence_floor?: number;
  staleness_months?: number;
  source_trust_order?: string[];
  user_agent?: string;
}

export interface TestConnectionResult {
  ok: boolean;
  message: string;
}

// ---------------------------------------------------------------------------
// JD Analysis types
// ---------------------------------------------------------------------------

export interface NamedGap {
  area: string;
  jd_requires: string;
  candidate_actual: string;
  severity: "low" | "med" | "high" | "blocker";
}

export interface HardBlocker {
  type: string;
  detail: string;
}

export interface RubricDimension {
  dimension: string;
  weight: number;
  raw: number;
  weighted: number;
  note: string;
}

export interface CompAssessment {
  posted: string | number | null;
  meets_floor: boolean | null;
  note: string;
}

export interface PositioningAssessment {
  aligned: boolean;
  note: string;
}

export interface CompanyFitAssessment {
  size_bucket: string | null;
  stage: string | null;
  remote_policy: string | null;
  note: string;
}

export interface TailoringGuidance {
  lead_with: string[];
  reframe_summary: string;
  do_not_claim: string[];
}

export interface JobAnalysisResult {
  id: number | null;
  job_id: number;
  provider: string;
  model: string;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  company: string;
  title: string;
  url: string;
  analyzed_at: string;
  verdict: "APPLY" | "CONDITIONAL" | "MONITOR" | "SKIP";
  weighted_score: number;
  one_line: string;
  named_gaps: NamedGap[];
  hard_blockers: HardBlocker[];
  rubric_breakdown: RubricDimension[];
  bonuses_applied: string[];
  penalties_applied: string[];
  comp: CompAssessment;
  positioning: PositioningAssessment;
  company_fit: CompanyFitAssessment;
  tailoring: TailoringGuidance;
  red_flags: string[];
  confidence: number;
}
