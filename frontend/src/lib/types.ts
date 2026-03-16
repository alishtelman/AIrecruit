// ── Auth ─────────────────────────────────────────────────────────────────────

export interface User {
  id: string;
  email: string;
  role: "candidate" | "company_admin" | "company_member";
  is_active: boolean;
  created_at: string;
}

export interface CompanyAssessment {
  id: string;
  employee_email: string;
  employee_name: string;
  target_role: string;
  status: "pending" | "in_progress" | "completed";
  invite_token: string;
  interview_id: string | null;
  report_id: string | null;
  created_at: string;
}

export interface CompanyMember {
  member_id: string | null;
  user_id: string;
  email: string;
  role: "admin" | "member";
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
  report_id: string;
  summary: ReportSummary;
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
}

export interface InterviewReplay {
  interview_id: string;
  candidate_name: string;
  target_role: string;
  completed_at: string | null;
  turns: ReplayTurn[];
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
  reports: ReportWithRole[];
}

// ── Report ────────────────────────────────────────────────────────────────────

export type HiringRecommendation = "strong_yes" | "yes" | "maybe" | "no";

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
  cheat_risk_score: number | null;
  cheat_flags: string[] | null;
}
