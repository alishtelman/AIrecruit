package db

import (
	"encoding/json"
	"time"

	"github.com/google/uuid"
)

// User represents the "users" table.
type User struct {
	ID             uuid.UUID `json:"id" db:"id"`
	Email          string    `json:"email" db:"email"`
	HashedPassword string    `json:"-" db:"hashed_password"`
	Role           string    `json:"role" db:"role"` // candidate | company_admin | company_member | platform_admin
	IsActive       bool      `json:"is_active" db:"is_active"`
	CreatedAt      time.Time `json:"created_at" db:"created_at"`
	UpdatedAt      time.Time `json:"updated_at" db:"updated_at"`
}

// Candidate represents the "candidates" table.
type Candidate struct {
	ID                uuid.UUID  `json:"id" db:"id"`
	UserID            uuid.UUID  `json:"user_id" db:"user_id"`
	FullName          string     `json:"full_name" db:"full_name"`
	SalaryMin         *int       `json:"salary_min" db:"salary_min"`
	SalaryMax         *int       `json:"salary_max" db:"salary_max"`
	SalaryCurrency    string     `json:"salary_currency" db:"salary_currency"`
	ProfileVisibility string     `json:"profile_visibility" db:"profile_visibility"` // private | marketplace | direct_link | request_only
	PublicShareToken  *string    `json:"public_share_token" db:"public_share_token"`
	CreatedAt         time.Time  `json:"created_at" db:"created_at"`
	UpdatedAt         time.Time  `json:"updated_at" db:"updated_at"`
}

// Company represents the "companies" table.
type Company struct {
	ID          uuid.UUID        `json:"id" db:"id"`
	OwnerUserID *uuid.UUID       `json:"owner_user_id" db:"owner_user_id"`
	Name        string           `json:"name" db:"name"`
	IsActive    bool             `json:"is_active" db:"is_active"`
	AISettings  *json.RawMessage `json:"ai_settings" db:"ai_settings"`
	CreatedAt   time.Time        `json:"created_at" db:"created_at"`
	UpdatedAt   time.Time        `json:"updated_at" db:"updated_at"`
}

// CompanyMember represents the "company_members" table.
type CompanyMember struct {
	ID              uuid.UUID  `json:"id" db:"id"`
	CompanyID       uuid.UUID  `json:"company_id" db:"company_id"`
	UserID          uuid.UUID  `json:"user_id" db:"user_id"`
	Role            string     `json:"role" db:"role"` // recruiter | viewer | admin
	InvitedByUserID *uuid.UUID `json:"invited_by_user_id" db:"invited_by_user_id"`
	CreatedAt       time.Time  `json:"created_at" db:"created_at"`
}

// Resume represents the "resumes" table.
type Resume struct {
	ID          uuid.UUID        `json:"id" db:"id"`
	CandidateID uuid.UUID        `json:"candidate_id" db:"candidate_id"`
	FileName    string           `json:"file_name" db:"file_name"`
	FilePath    string           `json:"file_path" db:"file_path"`
	FileSize    int              `json:"file_size" db:"file_size"`
	RawText     *string          `json:"raw_text" db:"raw_text"`
	ParsedJSON  *json.RawMessage `json:"parsed_json" db:"parsed_json"`
	IsActive    bool             `json:"is_active" db:"is_active"`
	CreatedAt   time.Time        `json:"created_at" db:"created_at"`
	UpdatedAt   time.Time        `json:"updated_at" db:"updated_at"`
}

// InterviewTemplate represents the "interview_templates" table.
type InterviewTemplate struct {
	ID          uuid.UUID        `json:"id" db:"id"`
	CompanyID   uuid.UUID        `json:"company_id" db:"company_id"`
	Name        string           `json:"name" db:"name"`
	TargetRole  string           `json:"target_role" db:"target_role"`
	Questions   json.RawMessage  `json:"questions" db:"questions"` // JSON array of string
	Description *string          `json:"description" db:"description"`
	IsPublic    bool             `json:"is_public" db:"is_public"`
	CreatedAt   time.Time        `json:"created_at" db:"created_at"`
}

// Interview represents the "interviews" table.
type Interview struct {
	ID                  uuid.UUID        `json:"id" db:"id"`
	CandidateID         uuid.UUID        `json:"candidate_id" db:"candidate_id"`
	ResumeID            *uuid.UUID       `json:"resume_id" db:"resume_id"`
	TemplateID          *uuid.UUID       `json:"template_id" db:"template_id"`
	Status              string           `json:"status" db:"status"` // created | in_progress | completed | report_generated | failed
	TargetRole          string           `json:"target_role" db:"target_role"`
	SeniorityLevel      *string          `json:"seniority_level" db:"seniority_level"` // junior | middle | senior
	QuestionCount       int              `json:"question_count" db:"question_count"`
	MaxQuestions        int              `json:"max_questions" db:"max_questions"`
	FollowupDepth       int              `json:"followup_depth" db:"followup_depth"`
	CreatedAt           time.Time        `json:"created_at" db:"created_at"`
	UpdatedAt           time.Time        `json:"updated_at" db:"updated_at"`
	Language            string           `json:"language" db:"language"`
	StartedAt           *time.Time       `json:"started_at" db:"started_at"`
	CompletedAt         *time.Time       `json:"completed_at" db:"completed_at"`
	RecordingPath       *string          `json:"recording_path" db:"recording_path"`
	CompanyAssessmentID *uuid.UUID       `json:"company_assessment_id" db:"company_assessment_id"`
	BehavioralSignals   *json.RawMessage `json:"behavioral_signals" db:"behavioral_signals"`
	InterviewState      *json.RawMessage `json:"interview_state" db:"interview_state"`
}

// InterviewMessage represents the "interview_messages" table.
type InterviewMessage struct {
	ID          uuid.UUID `json:"id" db:"id"`
	InterviewID uuid.UUID `json:"interview_id" db:"interview_id"`
	Role        string    `json:"role" db:"role"` // system | assistant | candidate
	Content     string    `json:"content" db:"content"`
	CreatedAt   time.Time `json:"created_at" db:"created_at"`
}

// AssessmentReport represents the "assessment_reports" table.
type AssessmentReport struct {
	ID                    uuid.UUID        `json:"id" db:"id"`
	InterviewID           uuid.UUID        `json:"interview_id" db:"interview_id"`
	CandidateID           uuid.UUID        `json:"candidate_id" db:"candidate_id"`
	OverallScore          *float64         `json:"overall_score" db:"overall_score"`
	HardSkillsScore       *float64         `json:"hard_skills_score" db:"hard_skills_score"`
	SoftSkillsScore       *float64         `json:"soft_skills_score" db:"soft_skills_score"`
	CommunicationScore    *float64         `json:"communication_score" db:"communication_score"`
	ProblemSolvingScore   *float64         `json:"problem_solving_score" db:"problem_solving_score"`
	Strengths             json.RawMessage  `json:"strengths" db:"strengths"`
	Weaknesses            json.RawMessage  `json:"weaknesses" db:"weaknesses"`
	Recommendations       json.RawMessage  `json:"recommendations" db:"recommendations"`
	HiringRecommendation  string           `json:"hiring_recommendation" db:"hiring_recommendation"` // strong_yes | yes | maybe | no
	InterviewSummary      *string          `json:"interview_summary" db:"interview_summary"`
	CompetencyScores      *json.RawMessage `json:"competency_scores" db:"competency_scores"`
	PerQuestionAnalysis   *json.RawMessage `json:"per_question_analysis" db:"per_question_analysis"`
	SkillTags             *json.RawMessage `json:"skill_tags" db:"skill_tags"`
	RedFlags              *json.RawMessage `json:"red_flags" db:"red_flags"`
	ResponseConsistency   *float64         `json:"response_consistency" db:"response_consistency"`
	OverallConfidence     *float64         `json:"overall_confidence" db:"overall_confidence"`
	CompetencyConfidence  *json.RawMessage `json:"competency_confidence" db:"competency_confidence"`
	ConfidenceReasons     *json.RawMessage `json:"confidence_reasons" db:"confidence_reasons"`
	EvidenceCoverage      *json.RawMessage `json:"evidence_coverage" db:"evidence_coverage"`
	DecisionPolicyVersion *string          `json:"decision_policy_version" db:"decision_policy_version"`
	CheatRiskScore        *float64         `json:"cheat_risk_score" db:"cheat_risk_score"`
	CheatFlags            *json.RawMessage `json:"cheat_flags" db:"cheat_flags"`
	FullReportJSON        json.RawMessage  `json:"full_report_json" db:"full_report_json"`
	ModelVersion          string           `json:"model_version" db:"model_version"`
	CreatedAt             time.Time        `json:"created_at" db:"created_at"`
	UpdatedAt             time.Time        `json:"updated_at" db:"updated_at"`
}

// CandidateSkill represents the "candidate_skills" table.
type CandidateSkill struct {
	ID              uuid.UUID `json:"id" db:"id"`
	CandidateID     uuid.UUID `json:"candidate_id" db:"candidate_id"`
	ReportID        uuid.UUID `json:"report_id" db:"report_id"`
	SkillName       string    `json:"skill_name" db:"skill_name"`
	Proficiency     string    `json:"proficiency" db:"proficiency"` // beginner | intermediate | advanced | expert
	EvidenceSummary *string   `json:"evidence_summary" db:"evidence_summary"`
	CreatedAt       time.Time `json:"created_at" db:"created_at"`
}

// CandidateAccessRequest represents the "candidate_access_requests" table.
type CandidateAccessRequest struct {
	ID                 uuid.UUID  `json:"id" db:"id"`
	CandidateID        uuid.UUID  `json:"candidate_id" db:"candidate_id"`
	CompanyID          uuid.UUID  `json:"company_id" db:"company_id"`
	RequestedByUserID  *uuid.UUID `json:"requested_by_user_id" db:"requested_by_user_id"`
	Status             string     `json:"status" db:"status"` // pending | approved | denied
	CreatedAt          time.Time  `json:"created_at" db:"created_at"`
	UpdatedAt          time.Time  `json:"updated_at" db:"updated_at"`
}

// CompanyCandidateNote represents the "company_candidate_notes" table.
type CompanyCandidateNote struct {
	ID           uuid.UUID  `json:"id" db:"id"`
	CompanyID    uuid.UUID  `json:"company_id" db:"company_id"`
	CandidateID  uuid.UUID  `json:"candidate_id" db:"candidate_id"`
	AuthorUserID *uuid.UUID `json:"author_user_id" db:"author_user_id"`
	Body         string     `json:"body" db:"body"`
	CreatedAt    time.Time  `json:"created_at" db:"created_at"`
	UpdatedAt    time.Time  `json:"updated_at" db:"updated_at"`
}

// CompanyCandidateActivity represents the "company_candidate_activities" table.
type CompanyCandidateActivity struct {
	ID           uuid.UUID        `json:"id" db:"id"`
	CompanyID    uuid.UUID        `json:"company_id" db:"company_id"`
	CandidateID  uuid.UUID        `json:"candidate_id" db:"candidate_id"`
	ActorUserID  *uuid.UUID       `json:"actor_user_id" db:"actor_user_id"`
	ActivityType string           `json:"activity_type" db:"activity_type"`
	Summary      string           `json:"summary" db:"summary"`
	Metadata     *json.RawMessage `json:"metadata" db:"metadata"`
	CreatedAt    time.Time        `json:"created_at" db:"created_at"`
}

// CompanyAssessment represents the "company_assessments" table.
type CompanyAssessment struct {
	ID                  uuid.UUID        `json:"id" db:"id"`
	CompanyID           uuid.UUID        `json:"company_id" db:"company_id"`
	CreatedByUserID     uuid.UUID        `json:"created_by_user_id" db:"created_by_user_id"`
	EmployeeEmail       string           `json:"employee_email" db:"employee_email"`
	EmployeeName        string           `json:"employee_name" db:"employee_name"`
	AssessmentType      string           `json:"assessment_type" db:"assessment_type"` // employee_internal
	TargetRole          string           `json:"target_role" db:"target_role"`
	TemplateID          *uuid.UUID       `json:"template_id" db:"template_id"`
	InviteToken         string           `json:"invite_token" db:"invite_token"`
	Status              string           `json:"status" db:"status"` // pending | opened | in_progress | completed | expired
	ModulePlan          *json.RawMessage `json:"module_plan" db:"module_plan"`
	CurrentModuleIndex  int              `json:"current_module_index" db:"current_module_index"`
	InterviewID         *uuid.UUID       `json:"interview_id" db:"interview_id"`
	DeadlineAt          *time.Time       `json:"deadline_at" db:"deadline_at"`
	ExpiresAt           *time.Time       `json:"expires_at" db:"expires_at"`
	OpenedAt            *time.Time       `json:"opened_at" db:"opened_at"`
	CompletedAt         *time.Time       `json:"completed_at" db:"completed_at"`
	BrandingName        *string          `json:"branding_name" db:"branding_name"`
	BrandingLogoURL     *string          `json:"branding_logo_url" db:"branding_logo_url"`
	CreatedAt           time.Time        `json:"created_at" db:"created_at"`
}

// HireOutcome represents the "hire_outcomes" table.
type HireOutcome struct {
	ID          uuid.UUID  `json:"id" db:"id"`
	CompanyID   uuid.UUID  `json:"company_id" db:"company_id"`
	CandidateID uuid.UUID  `json:"candidate_id" db:"candidate_id"`
	InterviewID *uuid.UUID `json:"interview_id" db:"interview_id"`
	Outcome     string     `json:"outcome" db:"outcome"` // hired | rejected | interviewing | no_show
	Notes       *string    `json:"notes" db:"notes"`
	CreatedAt   time.Time  `json:"created_at" db:"created_at"`
	UpdatedAt   time.Time  `json:"updated_at" db:"updated_at"`
}

// PlatformSettings represents the "platform_settings" table.
type PlatformSettings struct {
	ID                           int       `json:"id" db:"id"`
	CandidateRegistrationEnabled bool      `json:"candidate_registration_enabled" db:"candidate_registration_enabled"`
	CompanyRegistrationEnabled   bool      `json:"company_registration_enabled" db:"company_registration_enabled"`
	EmployeeInvitesEnabled       bool      `json:"employee_invites_enabled" db:"employee_invites_enabled"`
	MaintenanceModeEnabled       bool      `json:"maintenance_mode_enabled" db:"maintenance_mode_enabled"`
	ProctoringPolicyMode         *string   `json:"proctoring_policy_mode" db:"proctoring_policy_mode"`
	InterviewerModelPreference   *string   `json:"interviewer_model_preference" db:"interviewer_model_preference"`
	AssessorModelPreference      *string   `json:"assessor_model_preference" db:"assessor_model_preference"`
	LLMProvider                  *string   `json:"llm_provider" db:"llm_provider"`
	InterviewerModel             *string   `json:"interviewer_model" db:"interviewer_model"`
	AssessorModel                *string   `json:"assessor_model" db:"assessor_model"`
	InterviewerPromptOverride    *string   `json:"interviewer_prompt_override" db:"interviewer_prompt_override"`
	AssessorPromptOverride       *string   `json:"assessor_prompt_override" db:"assessor_prompt_override"`
	LLMTimeoutSeconds            *int      `json:"llm_timeout_seconds" db:"llm_timeout_seconds"`
	LLMMaxRetries                *int      `json:"llm_max_retries" db:"llm_max_retries"`
	CreatedAt                    time.Time `json:"created_at" db:"created_at"`
	UpdatedAt                    time.Time `json:"updated_at" db:"updated_at"`
}

// CompanyShortlist represents the "company_shortlists" table.
type CompanyShortlist struct {
	ID              uuid.UUID  `json:"id" db:"id"`
	CompanyID       uuid.UUID  `json:"company_id" db:"company_id"`
	CreatedByUserID *uuid.UUID `json:"created_by_user_id" db:"created_by_user_id"`
	Name            string     `json:"name" db:"name"`
	CreatedAt       time.Time  `json:"created_at" db:"created_at"`
}

// CompanyShortlistCandidate represents the "company_shortlist_candidates" table.
type CompanyShortlistCandidate struct {
	ID          uuid.UUID `json:"id" db:"id"`
	ShortlistID uuid.UUID `json:"shortlist_id" db:"shortlist_id"`
	CandidateID uuid.UUID `json:"candidate_id" db:"candidate_id"`
	CreatedAt   time.Time `json:"created_at" db:"created_at"`
}

// AdminAuditLog represents the "admin_audit_logs" table.
type AdminAuditLog struct {
	ID           uuid.UUID        `json:"id" db:"id"`
	ActorUserID  uuid.UUID        `json:"actor_user_id" db:"actor_user_id"`
	Action       string           `json:"action" db:"action"`
	EntityType   string           `json:"entity_type" db:"entity_type"`
	EntityID     *string          `json:"entity_id" db:"entity_id"`
	Summary      string           `json:"summary" db:"summary"`
	MetadataJSON *json.RawMessage `json:"metadata_json" db:"metadata_json"`
	CreatedAt    time.Time        `json:"created_at" db:"created_at"`
}
