/** Shared API types for Seeker OS backend. */

import type { components as ApiComponents } from "@/lib/api-schema";

export interface ApplicationEvent {
  id: number;
  job_id: number | null;
  event_type: string;
  actor: string;
  occurred_at: string;
  created_at: string;
  metadata: Record<string, unknown> | null;
  note: string | null;
}

/** Event enriched with job context for the global activity feed. */
export interface ActivityEvent extends ApplicationEvent {
  job_title: string | null;
  job_company: string | null;
}

/** Event types the user records by hand — the only editable/deletable ones. */
export const MANUAL_EVENT_TYPES = [
  "note",
  "call",
  "email_sent",
  "email_received",
  "meeting",
  "interview",
] as const;

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
  preference_rank: number | null;
  is_stale: boolean;
  days_since_last_activity: number | null;
  has_analysis: boolean;
  has_research: boolean;
  has_resume: boolean;
  analysis_verdict: string | null;
  net_score: number | null;
  score_modifiers: Record<string, number>;
  score_reasons: string[];
  has_recruiter: boolean;
  recruiter_source: string | null;
}

export type JobSortKey = "score" | "net_score" | "status" | "run_id" | "title" | "company" | "comp" | "location" | "ats" | "preference";
export type SortOrder = "asc" | "desc";

export type PaginatedJobsResponse = Omit<ApiComponents["schemas"]["PaginatedJobsResponse"], "jobs"> & {
  jobs: JobSummary[];
};

export interface RecruiterContact {
  id: number;
  recruiter_id: number;
  job_id: number;
  name: string | null;
  email: string | null;
  phone: string | null;
  linkedin: string | null;
  agency: string | null;
  source: string | null;
  contacted_at: string | null;
  notes: string | null;
  created_at: string;
  updated_at: string;
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
  recruiter_contacts: RecruiterContact[];
}

export interface JobCreateRequest {
  url?: string;
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
  recruiter_name?: string;
  recruiter_email?: string;
  recruiter_phone?: string;
  recruiter_linkedin?: string;
  recruiter_agency?: string;
  recruiter_source?: string;
  recruiter_contacted_at?: string;
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

export interface MovementEvent {
  job_id: number;
  job_title: string;
  company: string;
  event_type: string;
  from_status: string | null;
  to_status: string;
  occurred_at: string;
  actor: string;
  note: string | null;
}

export interface MovementReport {
  events: MovementEvent[];
  total: number;
  rejection_count: number;
  rejection_breakdown: Record<string, number>;
}

export interface AgingBucket {
  status: string;
  count: number;
  avg_days: number;
  max_days: number;
  stale_count: number;
}

export interface AgingReport {
  buckets: AgingBucket[];
  stale_after_days: number;
}

export interface VerdictDistribution {
  verdict: string;
  count: number;
  pct: number;
}

export interface SignalQualityReport {
  total_analyzed: number;
  verdicts: VerdictDistribution[];
  apply_rate: number;
  skip_rate: number;
  false_positive_pct: number;
  false_negative_pct: number;
  calibration_available: boolean;
  partial?: boolean;
  warnings?: string[];
}

export interface SpendByTask {
  task: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
}

export interface SpendByModel {
  provider: string;
  model: string;
  calls: number;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number;
  input_price_per_mtok: number | null;
  output_price_per_mtok: number | null;
  pricing_source: string;
  pricing_fetched_at: string | null;
}

export interface PricingRouteComparison {
  model: string;
  routes: { provider: string; input_price_per_mtok: number | null; output_price_per_mtok: number | null }[];
  variance_pct: number;
}

export interface SpendReport {
  total_calls: number;
  total_input_tokens: number;
  total_output_tokens: number;
  total_estimated_cost: number;
  pricing_configured: boolean;
  by_task: SpendByTask[];
  by_model: SpendByModel[];
  cost_per_ready: number | null;
  cost_per_applied: number | null;
  pricing_fetched_at: string | null;
  pricing_stale: boolean;
  pricing_stale_after_days: number;
  route_pricing: PricingRouteComparison[];
  partial?: boolean;
  warnings?: string[];
}

export interface ObservabilityOperation {
  operation_id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  calls: number;
  estimated_cost: number;
  validation_passed: boolean | null;
  artifact_type: string | null;
  artifact_id: number | null;
  job_id: number | null;
  job_title: string | null;
  company: string | null;
  task: string;
  grouped: boolean;
  model: string | null;
  total_tokens: number;
  latency_ms: number;
}

export interface ObservabilitySummary {
  total_calls: number;
  total_estimated_cost: number;
  failed_calls: number;
  truncated_calls: number;
  validation_pass_rate: number | null;
  unsupported_claims: number;
  overstated_claims: number;
  cost_per_passing_resume: number | null;
  historical_data_incomplete: boolean;
  available_tasks: string[];
  recent_operations: ObservabilityOperation[];
}

export interface ObservabilityTaskSummary {
  task: string;
  calls: number;
  estimated_cost: number;
  failed_calls: number;
  truncated_calls: number;
  avg_latency_ms: number;
  total_tokens: number;
  models_used: string[];
  validation_pass_rate: number | null;
  unsupported_claims: number;
  overstated_claims: number;
  cost_per_passing_resume: number | null;
}

export interface ObservabilityCall {
  call_id: string;
  parent_call_id: string | null;
  task: string;
  provider: string | null;
  model: string | null;
  status: string;
  error_type: string | null;
  stop_reason: string | null;
  temperature: number | null;
  max_tokens: number | null;
  prompt_name: string | null;
  prompt_version: string | null;
  route_reason: string | null;
  input_tokens: number;
  output_tokens: number;
  latency_ms: number;
  estimated_cost: number;
  started_at: string;
}

export interface ObservabilityEvaluation {
  evaluation_id: string;
  evaluator_name: string;
  evaluator_type: string;
  evaluator_version: string;
  metric_name: string;
  score: number | null;
  label: string | null;
  passed: boolean | null;
  evaluated_at: string;
}

export interface ObservabilityOperationDetail {
  operation_id: string;
  artifact_type: string | null;
  artifact_id: number | null;
  job_id: number | null;
  job_title: string | null;
  company: string | null;
  calls: ObservabilityCall[];
  evaluations: ObservabilityEvaluation[];
}

export interface LangfuseStatusResponse {
  enabled: boolean;
  initialized: boolean;
  base_url: string;
  capture_content: boolean;
  keys_configured: boolean;
  connection_ok: boolean;
}

export interface SLOMetric {
  name: string;
  target: number;
  actual: number;
  unit: string;
  passing: boolean;
}

export interface SLOStatusResponse {
  window_hours: number;
  metrics: SLOMetric[];
  daily_spend_usd: number;
  daily_spend_budget_usd: number;
}

export interface BudgetStatusResponse {
  adapter_type: string;
  daily_count: number;
  daily_cap: number;
  monthly_count: number;
  monthly_cap: number;
  daily_errors: number;
  daily_remaining: number | null;
  monthly_remaining: number | null;
}

export interface CostBucket {
  key: string;
  calls: number;
  cost_usd: number;
}

export interface CostSummaryResponse {
  total_calls: number;
  total_cost_usd: number;
  by_task: CostBucket[];
  by_artifact_type: CostBucket[];
}

export interface ArtifactCost {
  artifact_id: number;
  job_id: number | null;
  label: string;
  calls: number;
  cost_usd: number;
}

export interface CostPerArtifactResponse {
  avg_cost_per_analyzed_jd: number | null;
  avg_cost_per_tailored_resume: number | null;
  avg_cost_per_dossier: number | null;
  analyzed_jds: ArtifactCost[];
  tailored_resumes: ArtifactCost[];
  dossiers: ArtifactCost[];
}

export interface SkipReasonOption {
  key: string;
  label: string;
  hint: string;
  free_text: boolean;
}

export interface NoReasonSkip {
  job_id: number;
  title: string | null;
  company: string | null;
  status: string;
  event_id: number;
  event_type: string;
  occurred_at: string;
}

export interface SettingsResponse {
  filters: Record<string, unknown> | null;
  scoring: Record<string, unknown> | null;
  sources: Record<string, unknown> | null;
  profile_loaded: boolean;
  profile_configured: boolean;
  queries_count: number;
  skip_reasons: SkipReasonOption[];
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
  job_company: string;
  task: string;
  provider: string;
  model: string;
  validation_passed: boolean;
  validation_violations: Array<Record<string, unknown>>;
  input_tokens: number;
  output_tokens: number;
  estimated_cost: number | null;
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
  input_price_per_mtok: number | null;
  output_price_per_mtok: number | null;
  pricing_source: string | null;
}

export interface ProviderInfoResponse {
  id: string;
  type: string;
  label: string;
  enabled: boolean;
  auto_fetch_models: boolean;
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
  default_tier?: string | null;
}

export interface ProvidersConfigResponse {
  providers: ProviderInfoResponse[];
  tiers: Record<string, TierMappingResponse>;
  tasks: Record<string, TaskOverrideResponse>;
  partial?: boolean;
  warnings?: string[];
}

export interface MasterResumeInfo {
  path: string;
  exists: boolean;
  size_bytes: number;
  format: string;
  text_preview: string;
}

// Company Research types

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

// Company Research Settings types

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

// JD Analysis types

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
