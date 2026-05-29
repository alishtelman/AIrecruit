package main

import (
	"context"
	"encoding/json"
	"errors"
	"net/http"
	"sort"
	"time"

	"github.com/google/uuid"
)

type SalaryUpdateRequest struct {
	SalaryMin *int   `json:"salary_min"`
	SalaryMax *int   `json:"salary_max"`
	Currency  string `json:"currency"`
}

type SalaryResponse struct {
	SalaryMin      *int   `json:"salary_min"`
	SalaryMax      *int   `json:"salary_max"`
	SalaryCurrency string `json:"salary_currency"`
}

type BenchmarkBucket struct {
	ScoreRange string   `json:"score_range"`
	MedianMin  *float64 `json:"median_min"`
	MedianMax  *float64 `json:"median_max"`
	Count      int      `json:"count"`
}

type SalaryBenchmarkResponse struct {
	Role    string            `json:"role"`
	Buckets []BenchmarkBucket `json:"buckets"`
}

type CandidatePrivacyResponse struct {
	Visibility string  `json:"visibility"`
	ShareToken *string `json:"share_token"`
}

type CandidatePrivacyUpdateRequest struct {
	Visibility string `json:"visibility"`
}

type CandidateAccessRequestResponse struct {
	RequestID          uuid.UUID  `json:"request_id"`
	CompanyID          uuid.UUID  `json:"company_id"`
	CompanyName        string     `json:"company_name"`
	RequestedByUserID  *uuid.UUID `json:"requested_by_user_id"`
	RequestedByEmail   *string    `json:"requested_by_email"`
	Status             string     `json:"status"`
	CreatedAt          time.Time  `json:"created_at"`
	UpdatedAt          time.Time  `json:"updated_at"`
}

type SharedCandidateReportResponse struct {
	ReportID             string         `json:"report_id"`
	InterviewID          *string        `json:"interview_id"`
	TargetRole           string         `json:"target_role"`
	OverallScore         *float64       `json:"overall_score"`
	HiringRecommendation string         `json:"hiring_recommendation"`
	InterviewSummary     *string        `json:"interview_summary"`
	CompletedAt          *time.Time     `json:"completed_at"`
	Strengths            []string       `json:"strengths"`
	Recommendations      []string       `json:"recommendations"`
	SkillTags            []map[string]any `json:"skill_tags"`
}

type SharedCandidateProfileResponse struct {
	CandidateID       string                          `json:"candidate_id"`
	FullName          string                          `json:"full_name"`
	Visibility        string                          `json:"visibility"`
	RequiresApproval  bool                            `json:"requires_approval"`
	SalaryMin         *int                            `json:"salary_min"`
	SalaryMax         *int                            `json:"salary_max"`
	SalaryCurrency    string                          `json:"salary_currency"`
	Reports           []SharedCandidateReportResponse `json:"reports"`
}

func (srv *server) getCandidateContext(ctx context.Context, u User) (string, error) {
	if u.Role != "candidate" {
		return "", errors.New("user is not a candidate")
	}
	var candidateID string
	err := srv.db.QueryRow(ctx, "SELECT id FROM candidates WHERE user_id = $1", u.ID).Scan(&candidateID)
	if err != nil {
		return "", err
	}
	return candidateID, nil
}

func (srv *server) handleGetSalary(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var resp SalaryResponse
	err = srv.db.QueryRow(r.Context(), "SELECT salary_min, salary_max, salary_currency FROM candidates WHERE id = $1", candidateID).
		Scan(&resp.SalaryMin, &resp.SalaryMax, &resp.SalaryCurrency)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to retrieve salary")
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleUpdateSalary(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var req SalaryUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}
	if req.Currency == "" {
		req.Currency = "USD"
	}

	_, err = srv.db.Exec(r.Context(), "UPDATE candidates SET salary_min = $1, salary_max = $2, salary_currency = $3 WHERE id = $4",
		req.SalaryMin, req.SalaryMax, req.Currency, candidateID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to update salary")
		return
	}

	resp := SalaryResponse{
		SalaryMin:      req.SalaryMin,
		SalaryMax:      req.SalaryMax,
		SalaryCurrency: req.Currency,
	}
	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleSalaryBenchmark(w http.ResponseWriter, r *http.Request) {
	role := r.URL.Query().Get("role")
	if role == "" {
		writeError(w, http.StatusBadRequest, "role parameter is required")
		return
	}

	query := `
		SELECT c.salary_min, c.salary_max, r.overall_score
		FROM candidates c
		JOIN assessment_reports r ON r.candidate_id = c.id
		JOIN interviews i ON i.id = r.interview_id
		WHERE i.target_role = $1
		  AND c.salary_min IS NOT NULL
		  AND c.profile_visibility = 'marketplace'
	`
	rows, err := srv.db.Query(r.Context(), query, role)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to fetch benchmarks")
		return
	}
	defer rows.Close()

	type record struct {
		min   float64
		max   float64
		score *float64
	}
	var records []record
	for rows.Next() {
		var rec record
		var minInt int
		var maxInt *int
		if err := rows.Scan(&minInt, &maxInt, &rec.score); err != nil {
			continue
		}
		rec.min = float64(minInt)
		if maxInt != nil {
			rec.max = float64(*maxInt)
		} else {
			rec.max = float64(minInt)
		}
		records = append(records, rec)
	}

	bucketsData := map[string][]record{
		"0-4":  {},
		"5-6":  {},
		"7-8":  {},
		"9-10": {},
	}
	for _, rec := range records {
		b := "0-4"
		if rec.score != nil {
			if *rec.score <= 4 {
				b = "0-4"
			} else if *rec.score <= 6 {
				b = "5-6"
			} else if *rec.score <= 8 {
				b = "7-8"
			} else {
				b = "9-10"
			}
		}
		bucketsData[b] = append(bucketsData[b], rec)
	}

	median := func(vals []float64) *float64 {
		if len(vals) == 0 {
			return nil
		}
		sort.Float64s(vals)
		n := len(vals)
		var m float64
		if n%2 != 0 {
			m = vals[n/2]
		} else {
			m = (vals[n/2-1] + vals[n/2]) / 2.0
		}
		return &m
	}

	var buckets []BenchmarkBucket
	for _, key := range []string{"0-4", "5-6", "7-8", "9-10"} {
		var mins, maxs []float64
		for _, rec := range bucketsData[key] {
			mins = append(mins, rec.min)
			maxs = append(maxs, rec.max)
		}
		buckets = append(buckets, BenchmarkBucket{
			ScoreRange: key,
			MedianMin:  median(mins),
			MedianMax:  median(maxs),
			Count:      len(bucketsData[key]),
		})
	}

	resp := SalaryBenchmarkResponse{
		Role:    role,
		Buckets: buckets,
	}
	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleGetPrivacy(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var resp CandidatePrivacyResponse
	var rawShareToken *string
	err = srv.db.QueryRow(r.Context(), "SELECT profile_visibility, public_share_token FROM candidates WHERE id = $1", candidateID).
		Scan(&resp.Visibility, &rawShareToken)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to retrieve privacy")
		return
	}

	if resp.Visibility == "direct_link" || resp.Visibility == "request_only" {
		resp.ShareToken = rawShareToken
	}

	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleUpdatePrivacy(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var req CandidatePrivacyUpdateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}
	if req.Visibility != "marketplace" && req.Visibility != "direct_link" && req.Visibility != "request_only" {
		writeError(w, http.StatusBadRequest, "Unsupported visibility value")
		return
	}

	var rawShareToken *string
	err = srv.db.QueryRow(r.Context(), "SELECT public_share_token FROM candidates WHERE id = $1", candidateID).Scan(&rawShareToken)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to retrieve candidate")
		return
	}

	if (req.Visibility == "direct_link" || req.Visibility == "request_only") && rawShareToken == nil {
		token := uuid.New().String()
		rawShareToken = &token
	}

	_, err = srv.db.Exec(r.Context(), "UPDATE candidates SET profile_visibility = $1, public_share_token = $2 WHERE id = $3",
		req.Visibility, rawShareToken, candidateID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to update privacy")
		return
	}

	resp := CandidatePrivacyResponse{
		Visibility: req.Visibility,
	}
	if req.Visibility == "direct_link" || req.Visibility == "request_only" {
		resp.ShareToken = rawShareToken
	}
	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleGetSharedCandidateProfile(w http.ResponseWriter, r *http.Request) {
	shareToken := r.PathValue("share_token")
	if shareToken == "" {
		writeError(w, http.StatusBadRequest, "Missing share_token")
		return
	}

	var candidateID, fullName, visibility, currency string
	var minSalary, maxSalary *int
	err := srv.db.QueryRow(r.Context(), `
		SELECT id, full_name, profile_visibility, salary_min, salary_max, salary_currency 
		FROM candidates WHERE public_share_token = $1`, shareToken).
		Scan(&candidateID, &fullName, &visibility, &minSalary, &maxSalary, &currency)
	
	if err != nil {
		writeError(w, http.StatusNotFound, "Shared candidate profile not found.")
		return
	}

	if visibility != "marketplace" && visibility != "direct_link" && visibility != "request_only" {
		writeError(w, http.StatusNotFound, "Shared candidate profile not found.")
		return
	}

	resp := SharedCandidateProfileResponse{
		CandidateID:      candidateID,
		FullName:         fullName,
		Visibility:       visibility,
		RequiresApproval: visibility == "request_only",
		SalaryMin:        minSalary,
		SalaryMax:        maxSalary,
		SalaryCurrency:   currency,
		Reports:          []SharedCandidateReportResponse{},
	}

	if visibility != "request_only" {
		query := `
			SELECT r.id, r.interview_id, i.target_role, r.overall_score, r.hiring_recommendation, r.interview_summary, i.completed_at, r.strengths, r.recommendations, r.skill_tags
			FROM assessment_reports r
			JOIN interviews i ON i.id = r.interview_id
			WHERE r.candidate_id = $1 AND i.company_assessment_id IS NULL
			ORDER BY r.created_at DESC
		`
		rows, err := srv.db.Query(r.Context(), query, candidateID)
		if err == nil {
			defer rows.Close()
			for rows.Next() {
				var rep SharedCandidateReportResponse
				var strengthsBytes, recBytes, tagsBytes []byte
				if err := rows.Scan(&rep.ReportID, &rep.InterviewID, &rep.TargetRole, &rep.OverallScore, &rep.HiringRecommendation, &rep.InterviewSummary, &rep.CompletedAt, &strengthsBytes, &recBytes, &tagsBytes); err == nil {
					json.Unmarshal(strengthsBytes, &rep.Strengths)
					json.Unmarshal(recBytes, &rep.Recommendations)
					json.Unmarshal(tagsBytes, &rep.SkillTags)
					if rep.Strengths == nil {
						rep.Strengths = []string{}
					}
					if rep.Recommendations == nil {
						rep.Recommendations = []string{}
					}
					if rep.SkillTags == nil {
						rep.SkillTags = []map[string]any{}
					}
					resp.Reports = append(resp.Reports, rep)
				}
			}
		}
	}

	writeJSON(w, http.StatusOK, resp)
}
