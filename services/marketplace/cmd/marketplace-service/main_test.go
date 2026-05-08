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
	// args: company_id + q + recommendation + min_score + LIMIT
	if len(args) != 5 {
		encoded, _ := json.Marshal(args)
		t.Fatalf("unexpected args %s for query %s", encoded, query)
	}
	if args[len(args)-1] != maxMarketplaceRows {
		t.Fatalf("expected last arg to be LIMIT %d, got %v", maxMarketplaceRows, args[len(args)-1])
	}
}

func TestBuildMarketplaceQueryIncludesSkillsFilter(t *testing.T) {
	req := searchRequest{
		CompanyID: "00000000-0000-0000-0000-000000000001",
		Skills:    []string{"python", "sql"},
		Sort:      "score_desc",
	}
	query, args := buildMarketplaceQuery(req)

	if !strings.Contains(query, "unnest") {
		t.Fatalf("expected skills unnest clause in query: %s", query)
	}
	if !strings.Contains(query, "jsonb_array_elements(ar.skill_tags)") {
		t.Fatalf("expected skill_tags json filter in query: %s", query)
	}
	if !strings.Contains(query, "candidate_skills cs_filter") {
		t.Fatalf("expected candidate_skills fallback in query: %s", query)
	}
	// args: company_id + skills array + LIMIT
	if len(args) != 3 {
		encoded, _ := json.Marshal(args)
		t.Fatalf("unexpected args %s for query: %s", encoded, query)
	}
	skillsArg, ok := args[1].([]string)
	if !ok || len(skillsArg) != 2 {
		t.Fatalf("expected skills array as arg[1], got %T %v", args[1], args[1])
	}
}

func TestBuildMarketplaceQueryIncludesRowLimit(t *testing.T) {
	req := searchRequest{
		CompanyID: "00000000-0000-0000-0000-000000000001",
		Sort:      "score_desc",
	}
	query, args := buildMarketplaceQuery(req)

	if !strings.Contains(query, "LIMIT") {
		t.Fatalf("expected LIMIT in query: %s", query)
	}
	if args[len(args)-1] != maxMarketplaceRows {
		t.Fatalf("expected LIMIT arg=%d, got %v", maxMarketplaceRows, args[len(args)-1])
	}
}

func TestFilterBySkillsWithCandidateSkillsFallback(t *testing.T) {
	// Simulates Go post-processing where aggregated skill tags are set from
	// candidate_skills when report skill_tags were empty.
	items := []candidateItem{
		{
			CandidateID:         "c1",
			SkillTags:           []map[string]any{{"skill": "Python"}, {"skill": "SQL"}},
			reportSkillTagsEmpty: false,
		},
		{
			CandidateID:          "c2",
			SkillTags:            []map[string]any{{"skill": "Go"}},
			reportSkillTagsEmpty: true,
			aggregatedSkillTags:  []map[string]any{{"skill": "Python"}, {"skill": "Go"}},
		},
	}

	// c2's SkillTags are already set to aggregatedSkillTags by searchCandidates
	// before filterBySkills is called. Simulate that here:
	for i := range items {
		if items[i].reportSkillTagsEmpty && len(items[i].aggregatedSkillTags) > 0 {
			items[i].SkillTags = items[i].aggregatedSkillTags
		}
	}

	// Only c1 has both Python and SQL
	bothMatch := filterBySkills(items, []string{"python", "sql"})
	if len(bothMatch) != 1 || bothMatch[0].CandidateID != "c1" {
		t.Fatalf("expected only c1 to match python+sql: %#v", bothMatch)
	}

	// c2's aggregated tags include Python
	pythonMatch := filterBySkills(items, []string{"python"})
	if len(pythonMatch) != 2 {
		t.Fatalf("expected both candidates to match python: %#v", pythonMatch)
	}
}

func TestNormalizeDatabaseURLConvertsAsyncpgScheme(t *testing.T) {
	got := normalizeDatabaseURL("postgresql+asyncpg://user:pass@postgres:5432/db")
	if got != "postgres://user:pass@postgres:5432/db" {
		t.Fatalf("unexpected database url: %s", got)
	}
}
