// ── Auth ─────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  role: "candidate" | "company_admin" | "company_member" | "platform_admin";
  company_member_role?: "admin" | "recruiter" | "viewer" | null;
  company_id?: string | null;
  is_active: boolean;
  created_at: string;
}

export type AssessmentType = "employee_internal" | "candidate_external";
export type AssessmentModuleStatus = "pending" | "in_progress" | "completed" | "blocked";

export interface AdminOverviewMetrics {
  total_users: number;
  active_candidates: number;
  candidates_added_7d: number;
  total_companies: number;
  active_companies: number;
  companies_added_7d: number;
  company_members: number;
  interviews_total: number;
  interviews_started_7d: number;
  interviews_in_progress: number;
  interviews_completed: number;
  interviews_failed: number;
  completion_rate_pct: number;
  report_processing: number;
  reports_generated: number;
  reports_generated_7d: number;
  average_overall_score: number | null;
}

export interface AdminDailyTrendPoint {
  date: string;
  interviews_started: number;
  reports_generated: number;
  candidates_created: number;
  companies_created: number;
}

export interface AdminRuntimeStatus {
  app_env: string;
  rate_limit_enabled: boolean;
  platform_admin_bootstrap_enabled: boolean;
}

export interface AdminRecentUser {
  id: string;
  email: string;
  role: User["role"];
  is_active: boolean;
  created_at: string;
}

export interface AdminRecentCompany {
  id: string;
  name: string;
  owner_email: string | null;
  is_active: boolean;
  created_at: string;
}

export interface AdminRecentInterview {
  id: string;
  candidate_name: string;
  target_role: string;
  status: string;
  language: string;
  created_at: string;
  completed_at: string | null;
  report_ready: boolean;
}

export interface AdminRecentReport {
  id: string;
  candidate_name: string;
  target_role: string;
  overall_score: number | null;
  hiring_recommendation: "strong_yes" | "yes" | "maybe" | "no";
  created_at: string;
}

export interface AdminOverview {
  metrics: AdminOverviewMetrics;
  runtime: AdminRuntimeStatus;
  daily_trends: AdminDailyTrendPoint[];
  recent_users: AdminRecentUser[];
  recent_companies: AdminRecentCompany[];
  recent_interviews: AdminRecentInterview[];
  recent_reports: AdminRecentReport[];
}

export interface PlatformSettings {
  candidate_registration_enabled: boolean;
  company_registration_enabled: boolean;
  employee_invites_enabled: boolean;
  maintenance_mode_enabled: boolean;
  proctoring_policy_mode: "observe_only" | "strict_flagging" | string;
  interviewer_model_preference: string | null;
  assessor_model_preference: string | null;
  llm_provider: "openai" | string;
  interviewer_model: string;
  assessor_model: string;
  interviewer_prompt_override: string | null;
  assessor_prompt_override: string | null;
  llm_timeout_seconds: number;
  llm_max_retries: number;
  llm_model_options: Record<string, string[]>;
  llm_api_key_available: boolean;
  llm_required_api_key: string | null;
  llm_configuration_warning: string | null;
  tts_provider: string | null;
  tts_fallback_provider: string | null;
  created_at: string;
  updated_at: string;
}

export interface AdminAIRuntimeEvent {
  at: string | null;
  component: string | null;
  provider: string | null;
  model: string | null;
  note: string | null;
  error: string | null;
}

export interface AdminLLMDiagnostics {
  provider: string;
  interviewer_model: string;
  assessor_model: string;
  configured: boolean;
  api_key_available: boolean;
  required_api_key: string | null;
  configuration_warning: string | null;
  timeout_seconds: number;
  max_retries: number;
  runtime_provider: string;
  runtime_model: string;
  runtime_api_key_present: boolean;
  last_success: AdminAIRuntimeEvent | null;
  last_error: AdminAIRuntimeEvent | null;
  checked_at: string;
}

export interface AdminLLMPing {
  ok: boolean;
  provider: string;
  model: string;
  status: string;
  latency_ms: number | null;
  response_preview: string | null;
  error: string | null;
  created_at: string;
}

export interface AdminInterviewListItem {
  id: string;
  candidate_name: string;
  candidate_email: string;
  target_role: string;
  status: string;
  language: string;
  created_at: string;
  completed_at: string | null;
  report_id: string | null;
  overall_score: number | null;
  hiring_recommendation: "strong_yes" | "yes" | "maybe" | "no" | null;
  processing_state: "pending" | "processing" | "failed" | "ready" | string;
}

export interface AdminInterviewList {
  items: AdminInterviewListItem[];
}

export interface AdminUserListItem {
  id: string;
  email: string;
  role: User["role"];
  is_active: boolean;
  created_at: string;
}

export interface AdminUserList {
  items: AdminUserListItem[];
}

export interface AdminCompanyListItem {
  id: string;
  name: string;
  owner_email: string | null;
  is_active: boolean;
  member_count: number;
  assessments_total: number;
  assessments_in_progress: number;
  assessments_pending: number;
  assessments_completed: number;
  reports_generated: number;
  last_activity_at: string | null;
  created_at: string;
}

export interface AdminCompanyList {
  items: AdminCompanyListItem[];
}

export interface AdminReportListItem {
  id: string;
  candidate_name: string;
  candidate_email: string;
  target_role: string;
  overall_score: number | null;
  hiring_recommendation: "strong_yes" | "yes" | "maybe" | "no";
  created_at: string;
}

export interface AdminReportList {
  items: AdminReportListItem[];
}

export interface AdminAuditLogItem {
  id: string;
  actor_email: string;
  action: string;
  entity_type: string;
  entity_id: string | null;
  summary: string;
  metadata_json: Record<string, unknown> | null;
  created_at: string;
}

export interface AdminAuditLogList {
  items: AdminAuditLogItem[];
}

export interface AssessmentModulePlanItem {
  module_id: string;
  module_type: string;
  title: string;
  status: AssessmentModuleStatus;
  config: Record<string, unknown> | null;
  interview_id: string | null;
  started_at: string | null;
  completed_at: string | null;
  scenario_id?: string | null;
  scenario_title?: string | null;
  stack_focus?: string | null;
  preferred_language?: string | null;
  workspace_hint?: string | null;
}

export interface CompanyAssessment {
  id: string;
  employee_email: string;
  employee_name: string;
  assessment_type: AssessmentType;
  target_role: string;
  template_id: string | null;
  template_name: string | null;
  status: "pending" | "opened" | "in_progress" | "completed" | "expired";
  invite_token: string;
  interview_id: string | null;
  report_id: string | null;
  deadline_at: string | null;
  expires_at: string | null;
  opened_at: string | null;
  completed_at: string | null;
  branding_name: string | null;
  branding_logo_url: string | null;
  module_plan: AssessmentModulePlanItem[];
  module_count: number;
  current_module_index: number;
  current_module_type: string | null;
  created_at: string;
}

export interface EmployeeInviteInfo {
  assessment_id: string;
  employee_name: string;
  employee_email: string;
  assessment_type: AssessmentType;
  target_role: string;
  role_label: string;
  status: CompanyAssessment["status"];
  company_name: string;
  template_name: string | null;
  deadline_at: string | null;
  expires_at: string | null;
  branding_name: string | null;
  branding_logo_url: string | null;
  module_plan: AssessmentModulePlanItem[];
  module_count: number;
  current_module_index: number;
  current_module_type: string | null;
  current_module_title: string | null;
  current_module_preview: {
    scenario_id: string | null;
    scenario_title: string | null;
    scenario_prompt: string | null;
    stack_focus: string | null;
    preferred_language: string | null;
    workspace_hint: string | null;
  } | null;
  active_interview_id: string | null;
  can_start_current_module: boolean;
}

export interface CompanyMember {
  member_id: string | null;
  user_id: string;
  email: string;
  role: "admin" | "recruiter" | "viewer";
  created_at: string;
}

export interface CompanyAISettings {
  proctoring_policy_mode: "observe_only" | "strict_flagging";
  managed_by: "platform_admin" | string;
  message: string;
  tts_provider: string;
  tts_fallback_provider: string;
  runtime_applied_fields: string[];
  stored_preference_fields: string[];
}

export interface AssessmentModuleProfileOption {
  module_type: string;
  scenario_id: string;
  title: string;
  prompt: string;
  stack_focus: string | null;
  preferred_language: string | null;
  workspace_hint: string | null;
  recommended: boolean;
}

export interface AssessmentModuleProfiles {
  coding_task: AssessmentModuleProfileOption[];
  sql_live: AssessmentModuleProfileOption[];
  written_communication: AssessmentModuleProfileOption[];
}

export interface CandidateNote {
  note_id: string;
  body: string;
  author_user_id: string | null;
  author_email: string | null;
  created_at: string;
  updated_at: string;
}

export interface CandidateActivity {
  activity_id: string;
  activity_type: string;
  summary: string;
  actor_user_id: string | null;
  actor_email: string | null;
  metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface ShortlistMembership {
  shortlist_id: string;
  name: string;
}

export interface CompanyShortlist {
  shortlist_id: string;
  name: string;
  candidate_count: number;
  created_at: string;
}

export interface TokenResponse {
  access_token: string;
  token_type: string;
}

export interface LoginRequest {
  email: string;
  password: string;
}

export interface CandidateRegisterRequest {
  email: string;
  password: string;
  full_name: string;
}

// ── Candidate ─────────────────────────────────────────────────────────────────

export interface Candidate {
  id: string;
  user_id: string;
  full_name: string;
  created_at: string;
}

export interface CandidateWithUser {
  user: User;
  candidate: Candidate;
}

export type ProfileVisibility = "private" | "marketplace" | "direct_link" | "request_only";
export type AccessRequestStatus = "pending" | "approved" | "denied";

export interface CandidatePrivacy {
  visibility: ProfileVisibility;
  share_token: string | null;
}

export interface CandidateAccessRequest {
  request_id: string;
  company_id: string;
  company_name: string;
  requested_by_user_id: string | null;
  requested_by_email: string | null;
  status: AccessRequestStatus;
  created_at: string;
  updated_at: string;
}

export interface CompanyShareAccessStatus {
  candidate_id: string;
  full_name: string;
  request_status: AccessRequestStatus | null;
  can_open_company_workspace: boolean;
}

export interface SharedCandidateReport {
  report_id: string;
  interview_id: string | null;
  target_role: string;
  overall_score: number | null;
  hiring_recommendation: HiringRecommendation;
  interview_summary: string | null;
  completed_at: string | null;
  strengths: string[];
  recommendations: string[];
  skill_tags: SkillTag[] | null;
}

export interface SharedCandidateProfile {
  candidate_id: string;
  full_name: string;
  visibility: ProfileVisibility;
  requires_approval: boolean;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  reports: SharedCandidateReport[];
}

// ── Resume ────────────────────────────────────────────────────────────────────

export interface ResumeUploadResponse {
  resume_id: string;
  file_name: string;
  text_length: number;
  is_active: boolean;
}

export interface ActiveResume {
  resume_id: string;
  file_name: string;
  file_size: number;
  uploaded_at: string;
}

// ── Interview ─────────────────────────────────────────────────────────────────

export type TargetRole =
  | "backend_engineer"
  | "frontend_engineer"
  | "qa_engineer"
  | "devops_engineer"
  | "data_scientist"
  | "product_manager"
  | "mobile_engineer"
  | "designer";
export type InterviewSeniority = "junior" | "middle" | "senior";
export type InterviewStatus =
  | "created"
  | "in_progress"
  | "completed"
  | "report_processing"
  | "report_generated"
  | "failed";

export interface InterviewTemplate {
  template_id: string;
  company_id: string;
  name: string;
  target_role: TargetRole;
  questions: string[];
  description: string | null;
  is_public: boolean;
  created_at: string;
}

export interface StartInterviewRequest {
  target_role: TargetRole;
  template_id?: string | null;
  language?: "ru" | "en";
  seniority_level?: InterviewSeniority | null;
}

export interface StartInterviewResponse {
  interview_id: string;
  status: InterviewStatus;
  question_count: number;
  max_questions: number;
  core_question_count: number;
  asked_questions_count: number;
  answered_questions_count: number;
  current_question: string;
  seniority_level?: InterviewSeniority | null;
  interview_stage?: InterviewStage | null;
}

export interface SendMessageRequest {
  message: string;
}

export interface PracticalTask {
  task_id: string;
  task_type: string; // "coding_task" | "sql_task" | "qa_test_case_task" | "debugging_task" | "product_case_task" | "business_case_task"
  title: string;
  instruction: string;
  language?: string | null; // "python" | "javascript" | "sql" | "text" | "other"
  starter_code?: string | null;
  examples?: Array<{ input?: string; output?: string; description?: string }>;
  time_limit_minutes: number;
  evaluation_criteria: string[];
  voice_intro?: string | null;
}

export interface PracticalSubmissionRequest {
  task_id: string;
  task_type: string;
  answer: string;
  language?: string | null;
  duration_seconds?: number | null;
}

export interface SendMessageResponse {
  interview_id: string;
  status: InterviewStatus;
  question_count: number;
  max_questions: number;
  core_question_count: number;
  asked_questions_count: number;
  answered_questions_count: number;
  current_question: string | null;
  is_followup: boolean;
  question_type: string;
  interview_stage?: InterviewStage | null;
  module_session: InterviewModuleSession | null;
  question_delivery_type?: "voice_only" | "practical_task";
  practical_task?: PracticalTask | null;
}

export interface InterviewMessage {
  role: "assistant" | "candidate" | "system" | "practical_submission";
  content: string;
  created_at: string;
}

export interface InterviewListItem {
  interview_id: string;
  status: InterviewStatus;
  target_role: TargetRole;
  seniority_level?: InterviewSeniority | null;
  question_count: number;
  max_questions: number;
  core_question_count: number;
  asked_questions_count: number;
  answered_questions_count: number;
  started_at: string | null;
  completed_at: string | null;
  has_report: boolean;
  report_id: string | null;
}

export interface InterviewDetail {
  interview_id: string;
  status: InterviewStatus;
  target_role: TargetRole;
  seniority_level?: InterviewSeniority | null;
  question_count: number;
  max_questions: number;
  core_question_count: number;
  asked_questions_count: number;
  answered_questions_count: number;
  language?: string;
  started_at: string | null;
  completed_at: string | null;
  messages: InterviewMessage[];
  has_report: boolean;
  report_id: string | null;
  assessment_progress: AssessmentProgress | null;
  interview_stage?: InterviewStage | null;
  module_session: InterviewModuleSession | null;
}

export interface ResumeTextResponse {
  resume_id: number;
  file_name: string;
  raw_text: string;
}

export interface ReportSummary {
  overall_score: number | null;
  hiring_recommendation: HiringRecommendation;
  interview_summary: string | null;
}

export interface FinishInterviewResponse {
  interview_id: string;
  status: InterviewStatus;
  report_id: string | null;
  summary: ReportSummary | null;
  assessment_progress: AssessmentProgress | null;
  interview_stage?: InterviewStage | null;
  module_session: InterviewModuleSession | null;
}

export interface ReportProcessingDiagnostics {
  attempt_count: number;
  max_attempts: number;
  last_phase: string | null;
  last_status: "pending" | "processing" | "ready" | "failed" | null;
  last_started_at: string | null;
  last_completed_at: string | null;
  last_transition_at: string | null;
  next_retry_at: string | null;
  last_error: string | null;
  last_error_at: string | null;
}

export interface InterviewReportStatusResponse {
  interview_id: string;
  status: InterviewStatus;
  processing_state: "pending" | "processing" | "ready" | "failed";
  report_id: string | null;
  summary: ReportSummary | null;
  failure_reason?: string | null;
  diagnostics?: ReportProcessingDiagnostics | null;
  assessment_progress: AssessmentProgress | null;
  interview_stage?: InterviewStage | null;
  module_session: InterviewModuleSession | null;
}

export interface AssessmentProgress {
  assessment_id: string;
  invite_token: string;
  assessment_status: CompanyAssessment["status"];
  has_remaining_modules: boolean;
  module_count: number;
  current_module_index: number;
  current_module_type: string | null;
  current_module_title: string | null;
}

export interface InterviewModuleSession {
  module_type: string;
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  stack_focus: string | null;
  preferred_language: string | null;
  workspace_hint: string | null;
  stage_key: string | null;
  stage_title: string | null;
  stage_index: number;
  stage_count: number;
}

export interface InterviewStage {
  phase_key: string;
  phase_title: string;
  slot_number: number;
  slot_count: number;
  competency_targets: string[];
  resume_anchor: string | null;
  verification_target: string | null;
}

export interface CodingTaskArtifact {
  interview_id: string;
  language: string | null;
  code: string;
  updated_at: string | null;
}

export interface WrittenArtifact {
  interview_id: string;
  content: string;
  updated_at: string | null;
}

export interface ProctoringTimelineEvent {
  event_type: string;
  severity: "info" | "medium" | "high";
  occurred_at: string | null;
  source: string;
  details: Record<string, unknown>;
}

export interface ProctoringTimeline {
  interview_id: string;
  report_id: string | null;
  policy_mode: "observe_only" | "strict_flagging";
  risk_level: "low" | "medium" | "high";
  total_events: number;
  high_severity_count: number;
  speech_activity_pct: number | null;
  silence_pct: number | null;
  long_silence_count: number;
  speech_segment_count: number;
  events: ProctoringTimelineEvent[];
}

// ── Company ───────────────────────────────────────────────────────────────────

export interface CompanyRegisterRequest {
  email: string;
  password: string;
  company_name: string;
}

export interface CompanyRegisterResponse {
  user_id: string;
  email: string;
  company_id: string;
  company_name: string;
}

export interface CandidateListItem {
  candidate_id: string;
  full_name: string;
  email: string;
  target_role: string;
  overall_score: number | null;
  hiring_recommendation: HiringRecommendation;
  interview_summary: string | null;
  report_id: string;
  completed_at: string | null;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  hire_outcome: string | null;
  skill_tags: SkillTag[] | null;
  shortlists: ShortlistMembership[];
  cheat_risk_score: number | null;
  red_flag_count: number;
}

export interface CompanyCandidateSearchParams {
  q?: string;
  role?: string;
  skills?: string[];
  min_score?: number;
  recommendation?: HiringRecommendation | "";
  salary_min?: number;
  salary_max?: number;
  hire_outcome?: HireOutcome | "";
  shortlist_id?: string;
  sort?: "score_desc" | "score_asc" | "latest" | "salary_asc" | "salary_desc";
}

export type HireOutcome = "hired" | "rejected" | "interviewing" | "no_show";

export interface HireOutcomeResponse {
  outcome: HireOutcome;
  notes: string | null;
  updated_at: string;
}

export interface ReplayTurn {
  question_number: number;
  question: string;
  answer: string;
  question_time: string | null;
  answer_time: string | null;
  analysis: QuestionAnalysis | null;
  stage_key?: string | null;
  stage_title?: string | null;
}

export interface TranscriptBlock {
  speaker: "interviewer" | "candidate";
  kind: "question" | "answer";
  turn_number: number;
  text: string;
  timestamp: string | null;
}

export interface InterviewReplay {
  interview_id: string;
  candidate_id: string;
  candidate_name: string;
  target_role: string;
  seniority_level?: InterviewSeniority | null;
  completed_at: string | null;
  turns: ReplayTurn[];
  transcript_blocks?: TranscriptBlock[] | null;
  transcript_text?: string | null;
  module_session?: InterviewModuleSession | null;
}

export interface ReportWithRole {
  report_id: string;
  interview_id: string | null;
  target_role: string;
  overall_score: number | null;
  hard_skills_score: number | null;
  soft_skills_score: number | null;
  communication_score: number | null;
  problem_solving_score: number | null;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  hiring_recommendation: HiringRecommendation;
  interview_summary: string | null;
  created_at: string;
  competency_scores: CompetencyScore[] | null;
  skill_tags: SkillTag[] | null;
  red_flags: RedFlag[] | null;
  response_consistency: number | null;
}

export interface CandidateDetail {
  candidate_id: string;
  full_name: string;
  email: string;
  salary_min: number | null;
  salary_max: number | null;
  salary_currency: string;
  hire_outcome: string | null;
  hire_notes: string | null;
  shortlists: ShortlistMembership[];
  reports: ReportWithRole[];
}

export interface AnalyticsBreakdownItem {
  key: string;
  label: string;
  count: number;
}

export interface AnalyticsTemplatePerformance {
  template_id: string;
  template_name: string;
  target_role: string;
  completed_count: number;
  average_score: number | null;
}

export interface AnalyticsOverview {
  total_candidates: number;
  total_reports: number;
  shortlisted_candidates: number;
  role_breakdown: AnalyticsBreakdownItem[];
  recommendation_breakdown: AnalyticsBreakdownItem[];
  cheat_risk_breakdown: AnalyticsBreakdownItem[];
  red_flag_summary: {
    candidates_with_flags: number;
    total_flags: number;
  };
  template_performance: AnalyticsTemplatePerformance[];
}

export interface AnalyticsFunnelRow {
  recommendation: HiringRecommendation;
  total: number;
  unreviewed: number;
  interviewing: number;
  hired: number;
  rejected: number;
  no_show: number;
}

export interface AnalyticsFunnel {
  rows: AnalyticsFunnelRow[];
}

export interface AnalyticsSalaryBucket {
  score_range: string;
  median_min: number | null;
  median_max: number | null;
  count: number;
}

export interface AnalyticsSalaryOutcomeTrend {
  outcome: string;
  median_min: number | null;
  median_max: number | null;
  count: number;
}

export interface AnalyticsSalaryBand {
  candidate_count: number;
  range_min: number | null;
  median_min: number | null;
  median_max: number | null;
  range_max: number | null;
}

export interface AnalyticsSalaryRole {
  role: string;
  currency: string;
  candidate_count: number;
  market_band: AnalyticsSalaryBand;
  shortlisted_band: AnalyticsSalaryBand | null;
  buckets: AnalyticsSalaryBucket[];
  outcome_trends: AnalyticsSalaryOutcomeTrend[];
}

export interface AnalyticsSalary {
  role: string | null;
  shortlist_id: string | null;
  roles: AnalyticsSalaryRole[];
}

// ── Report ────────────────────────────────────────────────────────────────────

export type HiringRecommendation = "strong_yes" | "yes" | "maybe" | "no";

export interface ReportSummaryBlock {
  score: number | null;
  hiring_recommendation: HiringRecommendation;
  top_strengths: string[];
  top_weaknesses: string[];
}

export interface InterviewSummaryModel {
  topic_outcomes: Array<{
    slot: number;
    label: string;
    signal: string;
    outcome: string;
    verification_target: string | null;
    resume_anchor: string | null;
    evidence_hint: string | null;
    phase: string | null;
    block: string | null;
    tier: string | null;
    lead_question: string | null;
    allowed_probes: string[];
    scored_metrics: string[];
    why_asked: string | null;
    what_was_scored: string | null;
  }>;
  role: string;
  core_topics: number;
  total_turns: number;
  extra_turns: number;
  covered_competencies: number;
  coverage_label: string;
  signal_quality: string;
  validated_topics: number;
  partial_topics: number;
  unverified_claim_topics: number;
  honest_gaps: number;
  generic_or_evasive_topics: number;
  strong_topics: number;
}

export interface CompetencyScore {
  competency: string;
  category: string;
  score: number;
  weight: number;
  evidence: string;
  reasoning?: string;
}

export interface QuestionAnalysis {
  question_number: number;
  targeted_competencies: string[];
  answer_quality: number;
  evidence: string;
  skills_mentioned: { skill: string; proficiency: string }[];
  red_flags: string[];
  specificity: string;
  depth: string;
  ai_likelihood: number | null;
  stage_key?: string | null;
  stage_title?: string | null;
  block?: string | null;
  tier?: string | null;
  lead_question?: string | null;
  allowed_probes?: string[];
  scored_metrics?: string[];
  why_asked?: string | null;
  what_was_scored?: string | null;
}

export interface SkillTag {
  skill: string;
  proficiency: string;
  mentions_count: number;
}

export interface RedFlag {
  flag: string;
  evidence: string;
  severity: string;
}

export interface DevelopmentRoadmapPhase {
  phase_key: string;
  focus: string | null;
  actions: string[];
}

export interface DevelopmentRoadmap {
  phases: DevelopmentRoadmapPhase[];
}

export interface ExplainabilityEvidenceItem {
  question_number: number;
  topic: string;
  signal: string;
  outcome: string;
  answer_quality: number | null;
  evidence_excerpt: string;
  why_asked: string;
  what_was_scored: string;
  scored_metrics: string[];
}

export interface ExplainabilityStrengthItem {
  title: string;
  why_it_matters: string;
  evidence: ExplainabilityEvidenceItem[];
}

export interface ExplainabilityGapItem {
  title: string;
  risk: string;
  evidence: ExplainabilityEvidenceItem[];
}

export interface ExplainabilityRecommendationItem {
  title: string;
  linked_gap: string;
  actions: string[];
  success_criteria: string;
}

export interface ExplainabilityOverallAssessment {
  summary: string;
  overall_score: number;
  recommendation: HiringRecommendation;
  signal_quality: string;
  overall_confidence: number | null;
  score_method: string;
}

export interface ExplainabilityScoringTrace {
  pre_penalty_overall_score: number;
  post_penalty_overall_score: number;
  penalty_explanations: string[];
  top_block_signals: Array<{
    block: string;
    score: number;
    weight: number;
    question_count: number;
  }>;
}

export interface ExplainabilityReport {
  version: string;
  overall_assessment: ExplainabilityOverallAssessment;
  evidence_based_strengths: ExplainabilityStrengthItem[];
  evidence_based_gaps: ExplainabilityGapItem[];
  growth_recommendations: ExplainabilityRecommendationItem[];
  scoring_trace: ExplainabilityScoringTrace;
  summary_strengths: string[];
  summary_weaknesses: string[];
}

export interface AssessmentReport {
  id: string;
  interview_id: string;
  candidate_id: string;
  overall_score: number | null;
  hard_skills_score: number | null;
  soft_skills_score: number | null;
  communication_score: number | null;
  problem_solving_score: number | null;
  strengths: string[];
  weaknesses: string[];
  recommendations: string[];
  hiring_recommendation: HiringRecommendation;
  interview_summary: string | null;
  model_version: string;
  created_at: string;
  competency_scores: CompetencyScore[] | null;
  per_question_analysis: QuestionAnalysis[] | null;
  skill_tags: SkillTag[] | null;
  red_flags: RedFlag[] | null;
  response_consistency: number | null;
  overall_confidence: number | null;
  competency_confidence: Record<string, number> | null;
  confidence_reasons: string[] | null;
  evidence_coverage: Record<string, unknown> | null;
  decision_policy_version: string | null;
  cheat_risk_score: number | null;
  cheat_flags: string[] | null;
  summary: ReportSummaryBlock | null;
  development_roadmap: DevelopmentRoadmap | null;
  summary_model: InterviewSummaryModel | null;
  module_session: ReportModuleSession | null;
  proficiency_level: number | null;
  proficiency_band: string | null;
  proficiency_label: string | null;
  calibrated_scoring: Record<string, unknown> | null;
  explainability_report: ExplainabilityReport | null;
  system_design_summary: SystemDesignSummary | null;
  behavioral_interview_summary: BehavioralInterviewSummary | null;
  coding_task_summary: CodingTaskSummary | null;
  sql_live_summary: SqlLiveSummary | null;
  written_communication_summary: WrittenCommunicationSummary | null;
  practical_section: Record<string, unknown> | null;
  interview_quality_metrics: Record<string, number> | null;
  answer_quality_counters: Record<string, number> | null;
}

export interface ReportModuleSession {
  module_type: string;
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  stack_focus: string | null;
  preferred_language: string | null;
  workspace_hint: string | null;
  stage_key: string | null;
  stage_title: string | null;
  stage_index: number;
  stage_count: number;
}

export interface SystemDesignStageSummary {
  stage_key: string;
  stage_title: string;
  question_numbers: number[];
  average_answer_quality: number | null;
  stage_score: number | null;
  evidence_items: string[];
}

export interface SystemDesignRubricScore {
  rubric_key: string;
  score: number | null;
}

export interface SystemDesignSummary {
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  stage_count: number;
  overall_score: number | null;
  rubric_scores: SystemDesignRubricScore[];
  stages: SystemDesignStageSummary[];
}

export interface BehavioralInterviewStageSummary {
  stage_key: string;
  stage_title: string;
  question_numbers: number[];
  average_answer_quality: number | null;
  stage_score: number | null;
  evidence_items: string[];
}

export interface BehavioralInterviewRubricScore {
  rubric_key: string;
  score: number | null;
}

export interface BehavioralInterviewSummary {
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  stage_count: number;
  overall_score: number | null;
  ownership_score: number | null;
  collaboration_score: number | null;
  leadership_score: number | null;
  reflection_score: number | null;
  rubric_scores: BehavioralInterviewRubricScore[];
  stages: BehavioralInterviewStageSummary[];
  strengths: string[];
  gaps: string[];
  next_steps: string[];
}

export interface CodingTaskStageSummary {
  stage_key: string;
  stage_title: string;
  question_numbers: number[];
  average_answer_quality: number | null;
  stage_score: number | null;
  evidence_items: string[];
}

export interface CodingTaskRubricScore {
  rubric_key: string;
  score: number | null;
}

export interface CodingTaskCoverageCheck {
  check_key: string;
  title: string;
  status: "passed" | "partial" | "missed" | string;
  score: number | null;
  evidence: string | null;
}

export interface CodingTaskSummary {
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  stack_focus: string | null;
  preferred_language: string | null;
  workspace_hint: string | null;
  stage_count: number;
  overall_score: number | null;
  coverage_score: number | null;
  runner_score: number | null;
  stack_score: number | null;
  rubric_scores: CodingTaskRubricScore[];
  coverage_checks: CodingTaskCoverageCheck[];
  runner_checks: CodingTaskCoverageCheck[];
  stack_checks: CodingTaskCoverageCheck[];
  strengths: string[];
  gaps: string[];
  next_steps: string[];
  stages: CodingTaskStageSummary[];
  implementation_excerpt: string | null;
  has_code_submission: boolean;
  code_signal_score: number | null;
}

export interface SqlLiveStageSummary {
  stage_key: string;
  stage_title: string;
  question_numbers: number[];
  average_answer_quality: number | null;
  stage_score: number | null;
  evidence_items: string[];
}

export interface SqlLiveRubricScore {
  rubric_key: string;
  score: number | null;
}

export interface SqlLiveSummary {
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  stage_count: number;
  overall_score: number | null;
  validation_score: number | null;
  rubric_scores: SqlLiveRubricScore[];
  validation_checks: CodingTaskCoverageCheck[];
  stages: SqlLiveStageSummary[];
  query_excerpt: string | null;
  has_query_submission: boolean;
}

export interface WrittenCommunicationStageSummary {
  stage_key: string;
  stage_title: string;
  question_numbers: number[];
  average_answer_quality: number | null;
  stage_score: number | null;
  evidence_items: string[];
}

export interface WrittenCommunicationRubricScore {
  rubric_key: string;
  score: number | null;
}

export interface WrittenCommunicationSummary {
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
  workspace_hint: string | null;
  stage_count: number;
  overall_score: number | null;
  clarity_score: number | null;
  structure_score: number | null;
  audience_awareness_score: number | null;
  rubric_scores: WrittenCommunicationRubricScore[];
  stages: WrittenCommunicationStageSummary[];
  writing_excerpt: string | null;
  has_draft_submission: boolean;
  strengths: string[];
  gaps: string[];
  next_steps: string[];
}
