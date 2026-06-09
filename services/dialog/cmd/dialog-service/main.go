package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"fmt"
	"log"
	"net/http"
	"net/http/httputil"
	"net/url"
	"os"
	"strings"
	"time"

	"airecruit-db"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Config struct {
	DatabaseURL       string
	SecretKey         string
	SessionCookieName string
	Port              string
	BackendURL        string
}

type server struct {
	db           *pgxpool.Pool
	config       Config
	backendProxy *httputil.ReverseProxy
}

type User struct {
	ID        uuid.UUID
	Email     string
	Role      string
	IsActive  bool
	CompanyID *uuid.UUID
}

type Candidate struct {
	ID       uuid.UUID
	UserID   uuid.UUID
	FullName string
}

type InterviewListItemResponse struct {
	InterviewID            uuid.UUID  `json:"interview_id"`
	Status                 string     `json:"status"`
	TargetRole             string     `json:"target_role"`
	SeniorityLevel         *string    `json:"seniority_level"`
	QuestionCount          int        `json:"question_count"`
	MaxQuestions           int        `json:"max_questions"`
	CoreQuestionCount      int        `json:"core_question_count"`
	AskedQuestionsCount    int        `json:"asked_questions_count"`
	AnsweredQuestionsCount int        `json:"answered_questions_count"`
	StartedAt              *time.Time `json:"started_at"`
	CompletedAt            *time.Time `json:"completed_at"`
	HasReport              bool       `json:"has_report"`
	ReportID               *uuid.UUID `json:"report_id"`
}

func main() {
	config := loadConfig()

	ctx, cancel := context.WithTimeout(context.Background(), 30*time.Second)
	defer cancel()

	pool, err := db.Connect(ctx)
	if err != nil {
		log.Fatalf("Failed to initialize database: %v", err)
	}
	defer pool.Close()

	backendURL, err := url.Parse(config.BackendURL)
	if err != nil {
		log.Fatalf("Failed to parse backend URL: %v", err)
	}

	srv := &server{
		db:           pool,
		config:       config,
		backendProxy: httputil.NewSingleHostReverseProxy(backendURL),
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("GET /api/v1/interviews", srv.handleListInterviews)
	mux.HandleFunc("GET /api/v1/interviews/{interview_id}/report-status", srv.handleGetReportStatus)
	mux.HandleFunc("GET /api/v1/interviews/{interview_id}", srv.handleGetInterviewDetail)
	mux.HandleFunc("/", srv.handleFallbackProxy)

	log.Printf("Dialog service listening on port %s", config.Port)
	if err := http.ListenAndServe(config.Port, mux); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func (srv *server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	_, _ = w.Write([]byte(`{"status":"ok","service":"dialog-service"}`))
}

func (srv *server) handleListInterviews(w http.ResponseWriter, r *http.Request) {
	candidate, err := srv.authenticateCandidate(r)
	if err != nil {
		log.Printf("[DIALOG] Auth failure: %v", err)
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	query := `
		SELECT 
			i.id AS interview_id,
			i.status,
			i.target_role,
			i.seniority_level,
			i.question_count,
			i.max_questions,
			i.started_at,
			i.completed_at,
			r.id AS report_id
		FROM interviews i
		LEFT JOIN assessment_reports r ON r.interview_id = i.id
		WHERE i.candidate_id = $1
		ORDER BY i.started_at DESC NULLS LAST, i.created_at DESC
	`

	rows, err := srv.db.Query(r.Context(), query, candidate.ID)
	if err != nil {
		log.Printf("[DIALOG] Database query failed: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	defer rows.Close()

	items := []InterviewListItemResponse{}
	for rows.Next() {
		var item InterviewListItemResponse
		var startedAt, completedAt sql.NullTime
		var reportID uuid.NullUUID

		err := rows.Scan(
			&item.InterviewID,
			&item.Status,
			&item.TargetRole,
			&item.SeniorityLevel,
			&item.QuestionCount,
			&item.MaxQuestions,
			&startedAt,
			&completedAt,
			&reportID,
		)
		if err != nil {
			log.Printf("[DIALOG] Failed to scan row: %v", err)
			writeError(w, http.StatusInternalServerError, "Internal server error")
			return
		}

		if startedAt.Valid {
			item.StartedAt = &startedAt.Time
		}
		if completedAt.Valid {
			item.CompletedAt = &completedAt.Time
		}
		if reportID.Valid {
			item.HasReport = true
			item.ReportID = &reportID.UUID
		}

		// Calculate progress counters (asked and answered)
		asked, answered := srv.calculateProgressCounters(r.Context(), item.InterviewID, item.QuestionCount)
		item.CoreQuestionCount = item.QuestionCount
		item.AskedQuestionsCount = asked
		item.AnsweredQuestionsCount = answered

		items = append(items, item)
	}

	writeJSON(w, http.StatusOK, items)
}

func (srv *server) calculateProgressCounters(ctx context.Context, interviewID uuid.UUID, coreCount int) (asked, answered int) {
	// core_question_count is already provided
	// let's fetch interview_messages to count actual asked and answered questions
	var messages []struct {
		Role    string
		Content string
	}

	query := `
		SELECT role, content 
		FROM interview_messages 
		WHERE interview_id = $1 
		ORDER BY created_at ASC
	`
	rows, err := srv.db.Query(ctx, query, interviewID)
	if err != nil {
		return coreCount, coreCount
	}
	defer rows.Close()

	for rows.Next() {
		var m struct {
			Role    string
			Content string
		}
		if err := rows.Scan(&m.Role, &m.Content); err == nil {
			messages = append(messages, m)
		}
	}

	// Calculate asked and answered following interview_service.py logic
	askedCount := 0
	answeredCount := 0

	for _, msg := range messages {
		if msg.Role == "assistant" {
			askedCount++
		} else if msg.Role == "candidate" {
			answeredCount++
		}
	}

	return askedCount, answeredCount
}

func (srv *server) handleFallbackProxy(w http.ResponseWriter, r *http.Request) {
	log.Printf("[DIALOG FALLBACK] Proxying %s %s to legacy backend...", r.Method, r.URL.Path)
	srv.backendProxy.ServeHTTP(w, r)
}

// Authentication Helpers

func (srv *server) authenticateCandidate(r *http.Request) (Candidate, error) {
	var tokenStr string

	// 1. Try Authorization Bearer header first
	authHeader := r.Header.Get("Authorization")
	if strings.HasPrefix(authHeader, "Bearer ") {
		tStr := strings.TrimPrefix(authHeader, "Bearer ")
		token, err := jwt.Parse(tStr, func(token *jwt.Token) (interface{}, error) {
			if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
			}
			return []byte(srv.config.SecretKey), nil
		})
		if err == nil && token.Valid {
			tokenStr = tStr
		}
	}

	// 2. Try Cookie if Bearer was missing or invalid
	if tokenStr == "" {
		cookie, err := r.Cookie(srv.config.SessionCookieName)
		if err == nil {
			tokenStr = cookie.Value
		}
	}

	if tokenStr == "" {
		return Candidate{}, fmt.Errorf("no credentials found")
	}

	token, err := jwt.Parse(tokenStr, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(srv.config.SecretKey), nil
	})

	if err != nil || !token.Valid {
		return Candidate{}, fmt.Errorf("invalid token: %v", err)
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return Candidate{}, fmt.Errorf("invalid claims")
	}

	sub, ok := claims["sub"].(string)
	if !ok {
		return Candidate{}, fmt.Errorf("missing sub claim")
	}

	userID, err := uuid.Parse(sub)
	if err != nil {
		return Candidate{}, fmt.Errorf("invalid sub uuid: %v", err)
	}

	var u User
	err = srv.db.QueryRow(r.Context(), "SELECT id, email, role, is_active FROM users WHERE id = $1", userID).Scan(
		&u.ID, &u.Email, &u.Role, &u.IsActive,
	)
	if err != nil {
		return Candidate{}, err
	}

	if !u.IsActive {
		return Candidate{}, fmt.Errorf("user is inactive")
	}

	if u.Role != "candidate" {
		return Candidate{}, fmt.Errorf("user role is not candidate")
	}

	var c Candidate
	err = srv.db.QueryRow(r.Context(), "SELECT id, user_id, full_name FROM candidates WHERE user_id = $1", u.ID).Scan(
		&c.ID, &c.UserID, &c.FullName,
	)
	if err != nil {
		return Candidate{}, err
	}

	return c, nil
}

// Config Helpers

func loadConfig() Config {
	return Config{
		DatabaseURL:       db.GetDatabaseURL(),
		SecretKey:         envOrDefault("SECRET_KEY", "dev-secret-key-change-me"),
		SessionCookieName: envOrDefault("SESSION_COOKIE_NAME", "airecruit_session"),
		Port:              envOrDefault("PORT", ":8080"),
		BackendURL:        envOrDefault("BACKEND_URL", "http://backend:8000"),
	}
}

func envOrDefault(key string, fallback string) string {
	val := strings.TrimSpace(os.Getenv(key))
	if val == "" {
		return fallback
	}
	return val
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

// Structs and Handlers for GetInterviewDetail native implementation

type InterviewMessageResponse struct {
	Role      string    `json:"role"`
	Content   string    `json:"content"`
	CreatedAt time.Time `json:"created_at"`
}

type AssessmentProgressResponse struct {
	AssessmentID        uuid.UUID `json:"assessment_id"`
	InviteToken         string    `json:"invite_token"`
	AssessmentStatus    string    `json:"assessment_status"`
	HasRemainingModules bool      `json:"has_remaining_modules"`
	ModuleCount         int       `json:"module_count"`
	CurrentModuleIndex  int       `json:"current_module_index"`
	CurrentModuleType   *string   `json:"current_module_type"`
	CurrentModuleTitle  *string   `json:"current_module_title"`
}

type AssessmentModule struct {
	ModuleID    string `json:"module_id"`
	ModuleType  string `json:"module_type"`
	Title       string `json:"title"`
	Status      string `json:"status"`
	InterviewID string `json:"interview_id"`
}

type InterviewStageResponse struct {
	PhaseKey           string   `json:"phase_key"`
	PhaseTitle         string   `json:"phase_title"`
	SlotNumber         int      `json:"slot_number"`
	SlotCount          int      `json:"slot_count"`
	CompetencyTargets  []string `json:"competency_targets"`
	ResumeAnchor       *string  `json:"resume_anchor"`
	VerificationTarget *string  `json:"verification_target"`
}

type InterviewModuleSessionResponse struct {
	ModuleType        string  `json:"module_type"`
	ModuleTitle       *string `json:"module_title"`
	ScenarioID        *string `json:"scenario_id"`
	ScenarioTitle     *string `json:"scenario_title"`
	ScenarioPrompt    *string `json:"scenario_prompt"`
	StackFocus        *string `json:"stack_focus"`
	PreferredLanguage *string `json:"preferred_language"`
	WorkspaceHint     *string `json:"workspace_hint"`
	StageKey          *string `json:"stage_key"`
	StageTitle        *string `json:"stage_title"`
	StageIndex        int     `json:"stage_index"`
	StageCount        int     `json:"stage_count"`
}

type InterviewDetailResponse struct {
	InterviewID            uuid.UUID                       `json:"interview_id"`
	Status                 string                          `json:"status"`
	TargetRole             string                          `json:"target_role"`
	SeniorityLevel         *string                         `json:"seniority_level"`
	QuestionCount          int                             `json:"question_count"`
	MaxQuestions           int                             `json:"max_questions"`
	CoreQuestionCount      int                             `json:"core_question_count"`
	AskedQuestionsCount    int                             `json:"asked_questions_count"`
	AnsweredQuestionsCount int                             `json:"answered_questions_count"`
	Language               string                          `json:"language"`
	StartedAt              *time.Time                      `json:"started_at"`
	CompletedAt            *time.Time                      `json:"completed_at"`
	Messages               []InterviewMessageResponse      `json:"messages"`
	HasReport              bool                            `json:"has_report"`
	ReportID               *uuid.UUID                      `json:"report_id"`
	AssessmentProgress     *AssessmentProgressResponse     `json:"assessment_progress"`
	InterviewStage         *InterviewStageResponse         `json:"interview_stage"`
	ModuleSession          *InterviewModuleSessionResponse `json:"module_session"`
}

func (srv *server) handleGetInterviewDetail(w http.ResponseWriter, r *http.Request) {
	candidate, err := srv.authenticateCandidate(r)
	if err != nil {
		log.Printf("[DIALOG] Auth failure: %v", err)
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	interviewIDStr := r.PathValue("interview_id")
	interviewID, err := uuid.Parse(interviewIDStr)
	if err != nil {
		log.Printf("[DIALOG] Invalid interview_id %q: %v", interviewIDStr, err)
		writeError(w, http.StatusBadRequest, "Invalid interview ID")
		return
	}

	var status, targetRole, language string
	var seniorityLevel *string
	var questionCount, maxQuestions int
	var startedAt, completedAt *time.Time
	var companyAssessmentID *uuid.UUID
	var interviewStateRaw []byte

	query := `
		SELECT 
			status, target_role, seniority_level, question_count, max_questions, 
			language, started_at, completed_at, company_assessment_id, interview_state
		FROM interviews
		WHERE id = $1 AND candidate_id = $2
	`
	err = srv.db.QueryRow(r.Context(), query, interviewID, candidate.ID).Scan(
		&status,
		&targetRole,
		&seniorityLevel,
		&questionCount,
		&maxQuestions,
		&language,
		&startedAt,
		&completedAt,
		&companyAssessmentID,
		&interviewStateRaw,
	)
	if err != nil {
		log.Printf("[DIALOG] Interview not found or DB error: %v", err)
		writeError(w, http.StatusNotFound, "Interview not found.")
		return
	}

	// Fetch report if it exists
	var reportID *uuid.UUID
	err = srv.db.QueryRow(r.Context(), "SELECT id FROM assessment_reports WHERE interview_id = $1", interviewID).Scan(&reportID)
	if err != nil {
		// report not found, which is fine
		reportID = nil
	}

	// Fetch Visible Messages (filter out system/internal-only messages)
	var messages []InterviewMessageResponse
	msgQuery := `
		SELECT role, content, created_at 
		FROM interview_messages 
		WHERE interview_id = $1 
		ORDER BY created_at ASC
	`
	rows, err := srv.db.Query(r.Context(), msgQuery, interviewID)
	if err == nil {
		defer rows.Close()
		for rows.Next() {
			var m InterviewMessageResponse
			if err := rows.Scan(&m.Role, &m.Content, &m.CreatedAt); err == nil {
				if m.Role != "system" && m.Role != "practical_submission" {
					messages = append(messages, m)
				}
			}
		}
	}

	// Calculate asked and answered progress counters
	askedCount, answeredCount := srv.calculateProgressCounters(r.Context(), interviewID, questionCount)

	// Fetch Assessment Progress
	assessmentProgress, err := srv.fetchAssessmentProgress(r.Context(), companyAssessmentID, interviewID)
	if err != nil {
		log.Printf("[DIALOG] Failed to fetch assessment progress: %v", err)
	}

	// Build Stage and Session Payloads
	interviewStage := buildInterviewStagePayload(interviewStateRaw, questionCount, language)
	moduleSession := buildInterviewModuleSessionPayload(interviewStateRaw)

	detail := InterviewDetailResponse{
		InterviewID:            interviewID,
		Status:                 status,
		TargetRole:             targetRole,
		SeniorityLevel:         seniorityLevel,
		QuestionCount:          questionCount,
		MaxQuestions:           maxQuestions,
		CoreQuestionCount:      questionCount,
		AskedQuestionsCount:    askedCount,
		AnsweredQuestionsCount: answeredCount,
		Language:               language,
		StartedAt:              startedAt,
		CompletedAt:            completedAt,
		Messages:               messages,
		HasReport:              reportID != nil,
		ReportID:               reportID,
		AssessmentProgress:     assessmentProgress,
		InterviewStage:         interviewStage,
		ModuleSession:          moduleSession,
	}

	writeJSON(w, http.StatusOK, detail)
}

func (srv *server) fetchAssessmentProgress(ctx context.Context, companyAssessmentID *uuid.UUID, interviewID uuid.UUID) (*AssessmentProgressResponse, error) {
	if companyAssessmentID == nil {
		return nil, nil
	}

	var inviteToken, status, targetRole string
	var currentModuleIndex int
	var modulePlanRaw []byte
	var templateID *uuid.UUID

	query := `
		SELECT invite_token, status, current_module_index, module_plan, target_role, template_id
		FROM company_assessments
		WHERE id = $1
	`
	err := srv.db.QueryRow(ctx, query, *companyAssessmentID).Scan(
		&inviteToken,
		&status,
		&currentModuleIndex,
		&modulePlanRaw,
		&targetRole,
		&templateID,
	)
	if err != nil {
		return nil, err
	}

	var modulePlan []AssessmentModule
	if len(modulePlanRaw) > 0 {
		if err := json.Unmarshal(modulePlanRaw, &modulePlan); err != nil {
			return nil, err
		}
	}

	var currentModule *AssessmentModule
	if len(modulePlan) > 0 {
		idx := currentModuleIndex
		if idx < 0 {
			idx = 0
		}
		if idx >= len(modulePlan) {
			idx = len(modulePlan) - 1
		}
		currentModule = &modulePlan[idx]
	}

	res := &AssessmentProgressResponse{
		AssessmentID:        *companyAssessmentID,
		InviteToken:         inviteToken,
		AssessmentStatus:    status,
		HasRemainingModules: status != "completed" && status != "expired",
		ModuleCount:         len(modulePlan),
		CurrentModuleIndex:  currentModuleIndex,
	}

	if currentModule != nil {
		res.CurrentModuleType = &currentModule.ModuleType
		res.CurrentModuleTitle = &currentModule.Title
	}

	return res, nil
}

func buildInterviewStagePayload(stateRaw []byte, questionCount int, language string) *InterviewStageResponse {
	if len(stateRaw) == 0 {
		return nil
	}

	var state struct {
		ModuleType        string `json:"module_type"`
		CurrentTopicIndex *int   `json:"current_topic_index"`
		TopicPlan         []struct {
			Phase              string   `json:"phase"`
			Competencies       []string `json:"competencies"`
			ResumeAnchor       *string  `json:"resume_anchor"`
			VerificationTarget *string  `json:"verification_target"`
		} `json:"topic_plan"`
	}

	if err := json.Unmarshal(stateRaw, &state); err != nil {
		return nil
	}

	moduleType := strings.TrimSpace(strings.ToLower(state.ModuleType))
	if isStagedModuleType(moduleType) {
		return nil
	}

	if len(state.TopicPlan) == 0 {
		return nil
	}

	topicIdx := 0
	if state.CurrentTopicIndex != nil {
		topicIdx = *state.CurrentTopicIndex
	} else {
		topicIdx = questionCount - 1
	}

	if topicIdx < 0 {
		topicIdx = 0
	}
	if topicIdx >= len(state.TopicPlan) {
		topicIdx = len(state.TopicPlan) - 1
	}

	currentTopic := state.TopicPlan[topicIdx]
	phaseKey := strings.TrimSpace(strings.ToLower(currentTopic.Phase))
	if phaseKey == "" {
		phaseKey = "technical"
	}

	return &InterviewStageResponse{
		PhaseKey:           phaseKey,
		PhaseTitle:         phaseTitle(phaseKey, language),
		SlotNumber:         topicIdx + 1,
		SlotCount:          len(state.TopicPlan),
		CompetencyTargets:  currentTopic.Competencies,
		ResumeAnchor:       currentTopic.ResumeAnchor,
		VerificationTarget: currentTopic.VerificationTarget,
	}
}

func isStagedModuleType(mt string) bool {
	return mt == "system_design" || mt == "behavioral_interview" || mt == "coding_task" || mt == "sql_live" || mt == "written_communication"
}

func phaseTitle(phaseKey string, language string) string {
	titles := map[string]map[string]string{
		"intro": {
			"en": "Self-introduction",
			"ru": "О себе и опыте",
		},
		"resume_followup": {
			"en": "Resume follow-up",
			"ru": "Разбор опыта из резюме",
		},
		"technical": {
			"en": "Technical validation",
			"ru": "Техническая валидация",
		},
		"behavioral_closing": {
			"en": "Behavioral closing",
			"ru": "Финальный behavioral-блок",
		},
	}

	lang := "ru"
	if strings.TrimSpace(strings.ToLower(language)) == "en" {
		lang = "en"
	}

	if m, ok := titles[phaseKey]; ok {
		if t, ok := m[lang]; ok {
			return t
		}
	}

	formatted := strings.Title(strings.ReplaceAll(phaseKey, "_", " "))
	return formatted
}

func buildInterviewModuleSessionPayload(stateRaw []byte) *InterviewModuleSessionResponse {
	if len(stateRaw) == 0 {
		return nil
	}

	var state struct {
		ModuleType           string  `json:"module_type"`
		ModuleTitle          *string `json:"module_title"`
		ModuleScenarioID     *string `json:"module_scenario_id"`
		ModuleScenarioTitle  *string `json:"module_scenario_title"`
		ModuleScenarioPrompt *string `json:"module_scenario_prompt"`
		ModuleStackFocus     *string `json:"module_stack_focus"`
		ModulePrefLanguage   *string `json:"module_preferred_language"`
		ModuleWorkspaceHint  *string `json:"module_workspace_hint"`
		ModuleStageKey       *string `json:"module_stage_key"`
		ModuleStageTitle     *string `json:"module_stage_title"`
		ModuleStageIndex     *int    `json:"module_stage_index"`
		ModuleStagePlan      []struct {
			StageKey   string `json:"stage_key"`
			StageTitle string `json:"stage_title"`
		} `json:"module_stage_plan"`
	}

	if err := json.Unmarshal(stateRaw, &state); err != nil {
		return nil
	}

	moduleType := strings.TrimSpace(strings.ToLower(state.ModuleType))
	if moduleType == "" {
		return nil
	}

	stageCount := len(state.ModuleStagePlan)
	stageIdx := 0
	if state.ModuleStageIndex != nil {
		stageIdx = *state.ModuleStageIndex
	}
	if stageIdx < 0 {
		stageIdx = 0
	}
	if stageCount > 0 && stageIdx >= stageCount {
		stageIdx = stageCount - 1
	}

	var currentStageKey, currentStageTitle *string
	if stageCount > 0 {
		currentStageKey = &state.ModuleStagePlan[stageIdx].StageKey
		currentStageTitle = &state.ModuleStagePlan[stageIdx].StageTitle
	}

	if currentStageKey == nil || *currentStageKey == "" {
		currentStageKey = state.ModuleStageKey
	}
	if currentStageTitle == nil || *currentStageTitle == "" {
		currentStageTitle = state.ModuleStageTitle
	}

	title := state.ModuleTitle
	if title == nil || *title == "" {
		t := moduleTitleFallback(moduleType)
		title = &t
	}

	return &InterviewModuleSessionResponse{
		ModuleType:        moduleType,
		ModuleTitle:       title,
		ScenarioID:        state.ModuleScenarioID,
		ScenarioTitle:     state.ModuleScenarioTitle,
		ScenarioPrompt:    state.ModuleScenarioPrompt,
		StackFocus:        state.ModuleStackFocus,
		PreferredLanguage: state.ModulePrefLanguage,
		WorkspaceHint:     state.ModuleWorkspaceHint,
		StageKey:          currentStageKey,
		StageTitle:        currentStageTitle,
		StageIndex:        stageIdx,
		StageCount:        stageCount,
	}
}

func moduleTitleFallback(mt string) string {
	titles := map[string]string{
		"adaptive_interview":    "Adaptive Interview",
		"system_design":         "System Design",
		"coding_task":           "Coding Task",
		"behavioral_interview":  "Behavioral Interview",
		"written_communication": "Written Communication",
		"sql_live":              "SQL Live",
		"data_analysis":         "Data Analysis",
		"devops_incident":       "DevOps Incident",
	}
	if t, ok := titles[mt]; ok {
		return t
	}
	return strings.Title(strings.ReplaceAll(mt, "_", " "))
}

// ─── Report Status Handler ────────────────────────────────────────────────────

type ReportProcessingDiagnostics struct {
	AttemptCount    int     `json:"attempt_count"`
	MaxAttempts     int     `json:"max_attempts"`
	LastPhase       *string `json:"last_phase"`
	LastStatus      *string `json:"last_status"`
	LastStartedAt   *string `json:"last_started_at"`
	LastCompletedAt *string `json:"last_completed_at"`
	LastTransAt     *string `json:"last_transition_at"`
	NextRetryAt     *string `json:"next_retry_at"`
	LastError       *string `json:"last_error"`
	LastErrorAt     *string `json:"last_error_at"`
}

type ReportSummary struct {
	OverallScore          *float64 `json:"overall_score"`
	HiringRecommendation  *string  `json:"hiring_recommendation"`
	InterviewSummary      *string  `json:"interview_summary"`
}

type InterviewReportStatusResponse struct {
	InterviewID        uuid.UUID                   `json:"interview_id"`
	Status             string                      `json:"status"`
	ProcessingState    string                      `json:"processing_state"`
	ReportID           *uuid.UUID                  `json:"report_id"`
	Summary            *ReportSummary              `json:"summary"`
	FailureReason      *string                     `json:"failure_reason"`
	Diagnostics        *ReportProcessingDiagnostics `json:"diagnostics"`
	AssessmentProgress *AssessmentProgressResponse `json:"assessment_progress"`
	InterviewStage     *InterviewStageResponse     `json:"interview_stage"`
	ModuleSession      *InterviewModuleSessionResponse `json:"module_session"`
}

var validDiagnosticStatuses = map[string]bool{
	"pending": true, "processing": true, "ready": true, "failed": true,
}

func (srv *server) handleGetReportStatus(w http.ResponseWriter, r *http.Request) {
	candidate, err := srv.authenticateCandidate(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	interviewIDStr := r.PathValue("interview_id")
	interviewID, err := uuid.Parse(interviewIDStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Invalid interview ID")
		return
	}

	// Fetch interview core fields + state for diagnostics
	var interviewStatus, language string
	var companyAssessmentID *uuid.UUID
	var interviewStateRaw []byte

	query := `
		SELECT status, language, company_assessment_id, interview_state
		FROM interviews
		WHERE id = $1 AND candidate_id = $2
	`
	err = srv.db.QueryRow(r.Context(), query, interviewID, candidate.ID).Scan(
		&interviewStatus,
		&language,
		&companyAssessmentID,
		&interviewStateRaw,
	)
	if err != nil {
		log.Printf("[DIALOG] report-status: interview not found: %v", err)
		writeError(w, http.StatusNotFound, "Interview not found.")
		return
	}

	// Parse diagnostics from interview_state JSONB
	diagnostics := extractReportDiagnostics(interviewStateRaw)

	// Check if report exists
	var reportID *uuid.UUID
	var overallScore sql.NullFloat64
	var hiringRec, interviewSummary sql.NullString

	reportQuery := `
		SELECT id, overall_score, hiring_recommendation, interview_summary
		FROM assessment_reports
		WHERE interview_id = $1
		LIMIT 1
	`
	err = srv.db.QueryRow(r.Context(), reportQuery, interviewID).Scan(
		&reportID,
		&overallScore,
		&hiringRec,
		&interviewSummary,
	)
	reportExists := err == nil && reportID != nil

	// Fetch assessment progress
	assessmentProgress, _ := srv.fetchAssessmentProgress(r.Context(), companyAssessmentID, interviewID)

	// Build stage/module session payloads
	interviewStage := buildInterviewStagePayload(interviewStateRaw, 0, language)
	moduleSession := buildInterviewModuleSessionPayload(interviewStateRaw)

	if reportExists {
		// Auto-heal: if interview is not yet marked report_generated, we update it now
		// (Go service: we skip the write here — that's the Python monolith's job for now;
		// we just return the correct state so UI sees it as ready).
		if diagnostics != nil {
			ready := "ready"
			diagnostics.LastStatus = &ready
		}

		var summary *ReportSummary
		if overallScore.Valid || hiringRec.Valid || interviewSummary.Valid {
			s := &ReportSummary{}
			if overallScore.Valid {
				v := overallScore.Float64
				s.OverallScore = &v
			}
			if hiringRec.Valid {
				s.HiringRecommendation = &hiringRec.String
			}
			if interviewSummary.Valid {
				s.InterviewSummary = &interviewSummary.String
			}
			summary = s
		}

		writeJSON(w, http.StatusOK, InterviewReportStatusResponse{
			InterviewID:        interviewID,
			Status:             "report_generated",
			ProcessingState:    "ready",
			ReportID:           reportID,
			Summary:            summary,
			FailureReason:      nil,
			Diagnostics:        diagnostics,
			AssessmentProgress: assessmentProgress,
			InterviewStage:     interviewStage,
			ModuleSession:      moduleSession,
		})
		return
	}

	// No report yet — determine processing state from interview status
	var processingState string
	switch interviewStatus {
	case "failed":
		processingState = "failed"
	case "completed", "report_processing":
		processingState = "processing"
	default:
		processingState = "pending"
	}

	var failureReason *string
	if processingState == "failed" {
		if diagnostics != nil && diagnostics.LastError != nil {
			failureReason = diagnostics.LastError
		} else {
			reason := "Report generation failed."
			failureReason = &reason
		}
	}

	// If processing, kick the Python backend to schedule work (via internal call)
	// For now: we just return state; retry logic remains in Python monolith.
	writeJSON(w, http.StatusOK, InterviewReportStatusResponse{
		InterviewID:        interviewID,
		Status:             interviewStatus,
		ProcessingState:    processingState,
		ReportID:           nil,
		Summary:            nil,
		FailureReason:      failureReason,
		Diagnostics:        diagnostics,
		AssessmentProgress: assessmentProgress,
		InterviewStage:     interviewStage,
		ModuleSession:      moduleSession,
	})
}

func extractReportDiagnostics(stateRaw []byte) *ReportProcessingDiagnostics {
	if len(stateRaw) == 0 {
		return nil
	}

	var state struct {
		ReportDiagnostics *struct {
			AttemptCount  int     `json:"attempt_count"`
			MaxAttempts   int     `json:"max_attempts"`
			LastPhase     *string `json:"last_phase"`
			LastStatus    *string `json:"last_status"`
			LastStartedAt *string `json:"last_started_at"`
			LastCompAt    *string `json:"last_completed_at"`
			LastTransAt   *string `json:"last_transition_at"`
			NextRetryAt   *string `json:"next_retry_at"`
			LastError     *string `json:"last_error"`
			LastErrorAt   *string `json:"last_error_at"`
		} `json:"report_diagnostics"`
	}

	if err := json.Unmarshal(stateRaw, &state); err != nil || state.ReportDiagnostics == nil {
		return nil
	}

	raw := state.ReportDiagnostics

	// Validate last_status
	if raw.LastStatus != nil && !validDiagnosticStatuses[*raw.LastStatus] {
		raw.LastStatus = nil
	}

	return &ReportProcessingDiagnostics{
		AttemptCount:    raw.AttemptCount,
		MaxAttempts:     raw.MaxAttempts,
		LastPhase:       raw.LastPhase,
		LastStatus:      raw.LastStatus,
		LastStartedAt:   raw.LastStartedAt,
		LastCompletedAt: raw.LastCompAt,
		LastTransAt:     raw.LastTransAt,
		NextRetryAt:     raw.NextRetryAt,
		LastError:       raw.LastError,
		LastErrorAt:     raw.LastErrorAt,
	}
}
