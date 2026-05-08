package main

import (
	"context"
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
)

func TestHandleSearchUsesInjectedSearchAndNormalizesPayload(t *testing.T) {
	var captured searchRequest
	srv := &server{
		search: func(ctx context.Context, req searchRequest) ([]candidateItem, error) {
			captured = req
			score := 8.5
			summary := "Strong candidate"
			return []candidateItem{{
				CandidateID:          "00000000-0000-0000-0000-000000000001",
				FullName:             "Candidate",
				Email:                "candidate@example.com",
				TargetRole:           "backend_engineer",
				OverallScore:         &score,
				HiringRecommendation: "yes",
				InterviewSummary:     &summary,
				ReportID:             "00000000-0000-0000-0000-000000000002",
				SalaryCurrency:       "USD",
				SkillTags:            []map[string]any{{"skill": "Go", "proficiency": "advanced"}},
				Shortlists:           []shortlistMembership{},
			}}, nil
		},
	}
	req := httptest.NewRequest(
		http.MethodPost,
		"/v1/company-candidates/search",
		strings.NewReader(`{"company_id":" company-1 ","skills":[" Go ",""],"sort":""}`),
	)
	rec := httptest.NewRecorder()

	srv.handleSearch(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if captured.CompanyID != "company-1" || captured.Sort != "score_desc" {
		t.Fatalf("payload was not normalized: %#v", captured)
	}
	if len(captured.Skills) != 1 || captured.Skills[0] != "go" {
		t.Fatalf("skills were not normalized: %#v", captured.Skills)
	}
	if !strings.Contains(rec.Body.String(), `"candidate_id"`) {
		t.Fatalf("expected candidate payload: %s", rec.Body.String())
	}
}

func TestHandleSearchRejectsInvalidPayload(t *testing.T) {
	srv := &server{search: func(ctx context.Context, req searchRequest) ([]candidateItem, error) {
		t.Fatal("search should not be called")
		return nil, nil
	}}
	req := httptest.NewRequest(http.MethodPost, "/v1/company-candidates/search", strings.NewReader(`{"company_id":""}`))
	rec := httptest.NewRecorder()

	srv.handleSearch(rec, req)

	if rec.Code != http.StatusUnprocessableEntity {
		t.Fatalf("expected 422, got %d", rec.Code)
	}
}

func TestHandleStatusDoesNotExposeDatabaseURL(t *testing.T) {
	srv := &server{}
	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	rec := httptest.NewRecorder()

	srv.handleStatus(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	body := rec.Body.String()
	if strings.Contains(body, "postgres") || strings.Contains(body, "password") {
		t.Fatalf("status leaked database details: %s", body)
	}
	if !strings.Contains(body, `"database_configured":false`) {
		t.Fatalf("expected database configured flag: %s", body)
	}
}

func TestFilterBySkillsUsesRenderedSkillTags(t *testing.T) {
	items := []candidateItem{
		{
			CandidateID: "candidate-1",
			SkillTags:   []map[string]any{{"skill": "Python"}},
		},
		{
			CandidateID: "candidate-2",
			SkillTags:   []map[string]any{{"skill": "Go"}},
		},
	}

	pythonMatches := filterBySkills(items, []string{"python"})
	if len(pythonMatches) != 1 || pythonMatches[0].CandidateID != "candidate-1" {
		t.Fatalf("expected only candidate-1 to match Python: %#v", pythonMatches)
	}

	goMatches := filterBySkills(items, []string{"go"})
	if len(goMatches) != 1 || goMatches[0].CandidateID != "candidate-2" {
		t.Fatalf("expected only candidate-2 to match Go: %#v", goMatches)
	}
}

func TestBuildMarketplaceQueryIncludesLatestReportWindow(t *testing.T) {
	minScore := 7.0
	req := searchRequest{
		CompanyID:      "00000000-0000-0000-0000-000000000001",
		Q:              "alice",
		MinScore:       &minScore,
		Recommendation: "yes",
		Sort:           "latest",
	}
	query, args := buildMarketplaceQuery(req)

	if !strings.Contains(query, "ROW_NUMBER() OVER") || !strings.Contains(query, "PARTITION BY ar.candidate_id") {
		t.Fatalf("query missing latest report window: %s", query)
	}
	if !strings.Contains(query, "ORDER BY i.completed_at DESC, ar.created_at DESC") {
		t.Fatalf("query missing latest sort: %s", query)
	}
	if len(args) != 4 {
		encoded, _ := json.Marshal(args)
		t.Fatalf("unexpected args %s for query %s", encoded, query)
	}
}

func TestNormalizeDatabaseURLConvertsAsyncpgScheme(t *testing.T) {
	got := normalizeDatabaseURL("postgresql+asyncpg://user:pass@postgres:5432/db")
	if got != "postgres://user:pass@postgres:5432/db" {
		t.Fatalf("unexpected database url: %s", got)
	}
}
