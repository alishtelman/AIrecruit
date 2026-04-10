// ── Auth ─────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  role: "candidate" | "company_admin" | "company_member";
  company_member_role?: "admin" | "recruiter" | "viewer" | null;
  company_id?: string | null;
  is_active: boolean;
  created_at: string;
}

export type AssessmentType = "employee_internal" | "candidate_external";
export type AssessmentModuleStatus = "pending" | "in_progress" | "completed" | "blocked";

export interface AssessmentModulePlanItem {
  module_id: string;
  module_type: string;
  title: string;
  status: AssessmentModuleStatus;
  config: Record<string, unknown> | null;
  interview_id: string | null;
  started_at: string | null;
  completed_at: string | null;
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
  interviewer_provider: string;
  interviewer_runtime_model: string;
  interviewer_model_preference: string | null;
  assessor_provider: string;
  assessor_runtime_model: string;
  assessor_model_preference: string | null;
  tts_provider: string;
  tts_fallback_provider: string;
  mock_ai_available: boolean;
  runtime_applied_fields: string[];
  stored_preference_fields: string[];
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
}

export interface StartInterviewResponse {
  interview_id: string;
  status: InterviewStatus;
  question_count: number;
  max_questions: number;
  current_question: string;
}

export interface SendMessageRequest {
  message: string;
}

export interface SendMessageResponse {
  interview_id: string;
  status: InterviewStatus;
  question_count: number;
  max_questions: number;
  current_question: string | null;
  is_followup: boolean;
  question_type: string;
  module_session: InterviewModuleSession | null;
}

export interface InterviewMessage {
  role: "assistant" | "candidate" | "system";
  content: string;
  created_at: string;
}

export interface InterviewListItem {
  interview_id: string;
  status: InterviewStatus;
  target_role: TargetRole;
  question_count: number;
  max_questions: number;
  started_at: string | null;
  completed_at: string | null;
  has_report: boolean;
  report_id: string | null;
}

export interface InterviewDetail {
  interview_id: string;
  status: InterviewStatus;
  target_role: TargetRole;
  question_count: number;
  max_questions: number;
  language?: string;
  started_at: string | null;
  completed_at: string | null;
  messages: InterviewMessage[];
  has_report: boolean;
  report_id: string | null;
  assessment_progress: AssessmentProgress | null;
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
  stage_key: string | null;
  stage_title: string | null;
  stage_index: number;
  stage_count: number;
}

export interface CodingTaskArtifact {
  interview_id: string;
  language: string | null;
  code: string;
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
  system_design_summary: SystemDesignSummary | null;
  coding_task_summary: CodingTaskSummary | null;
}

export interface ReportModuleSession {
  module_type: string;
  module_title: string | null;
  scenario_id: string | null;
  scenario_title: string | null;
  scenario_prompt: string | null;
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
  stage_count: number;
  overall_score: number | null;
  coverage_score: number | null;
  runner_score: number | null;
  rubric_scores: CodingTaskRubricScore[];
  coverage_checks: CodingTaskCoverageCheck[];
  runner_checks: CodingTaskCoverageCheck[];
  stages: CodingTaskStageSummary[];
  implementation_excerpt: string | null;
  has_code_submission: boolean;
  code_signal_score: number | null;
}
