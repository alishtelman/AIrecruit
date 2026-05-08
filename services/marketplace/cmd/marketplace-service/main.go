package main

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"net/http"
	"os"
	"sort"
	"strconv"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

const (
	defaultListenAddr  = ":8080"
	maxMarketplaceRows = 500
)

var allowedSorts = map[string]bool{
	"latest":      true,
	"salary_asc":  true,
	"salary_desc": true,
	"score_asc":   true,
	"score_desc":  true,
}

type searchRequest struct {
	CompanyID      string   `json:"company_id"`
	Q              string   `json:"q"`
	Role           string   `json:"role"`
	Skills         []string `json:"skills"`
	MinScore       *float64 `json:"min_score"`
	Recommendation string   `json:"recommendation"`
	SalaryMin      *int     `json:"salary_min"`
	SalaryMax      *int     `json:"salary_max"`
	HireOutcome    string   `json:"hire_outcome"`
	ShortlistID    string   `json:"shortlist_id"`
	Sort           string   `json:"sort"`
}

type candidateItem struct {
	CandidateID          string                `json:"candidate_id"`
	FullName             string                `json:"full_name"`
	Email                string                `json:"email"`
	TargetRole           string                `json:"target_role"`
	OverallScore         *float64              `json:"overall_score"`
	HiringRecommendation string                `json:"hiring_recommendation"`
	InterviewSummary     *string               `json:"interview_summary"`
	ReportID             string                `json:"report_id"`
	CompletedAt          *time.Time            `json:"completed_at"`
	SalaryMin            *int                  `json:"salary_min"`
	SalaryMax            *int                  `json:"salary_max"`
	SalaryCurrency       string                `json:"salary_currency"`
	HireOutcome          *string               `json:"hire_outcome"`
	SkillTags            []map[string]any      `json:"skill_tags"`
	Shortlists           []shortlistMembership `json:"shortlists"`
	CheatRiskScore       *float64              `json:"cheat_risk_score"`
	RedFlagCount         int                   `json:"red_flag_count"`
	aggregatedSkillTags  []map[string]any      `json:"-"`
	reportSkillTagsEmpty bool                  `json:"-"`
}

type shortlistMembership struct {
	ShortlistID string `json:"shortlist_id"`
	Name        string `json:"name"`
}

type providerError struct {
	status int
	detail string
}

func (e providerError) Error() string {
	return e.detail
}

type server struct {
	db     *pgxpool.Pool
	search func(context.Context, searchRequest) ([]candidateItem, error)
}

func main() {
	databaseURL := normalizeDatabaseURL(os.Getenv("DATABASE_URL"))
	var pool *pgxpool.Pool
	if databaseURL != "" {
		var err error
		pool, err = pgxpool.New(context.Background(), databaseURL)
		if err != nil {
			panic(err)
		}
		defer pool.Close()
	}

	srv := &server{db: pool}
	srv.search = srv.searchCandidates

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("GET /v1/status", srv.handleStatus)
	mux.HandleFunc("POST /v1/company-candidates/search", srv.handleSearch)

	addr := envOrDefault("MARKETPLACE_SERVICE_ADDR", defaultListenAddr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		panic(err)
	}
}

func (s *server) handleHealth(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"status":              "ok",
		"service":             "marketplace-service",
		"database_configured": s.db != nil,
	})
}

func (s *server) handleStatus(w http.ResponseWriter, _ *http.Request) {
	writeJSON(w, http.StatusOK, map[string]any{
		"service":                       "marketplace-service",
		"database_configured":           s.db != nil,
		"endpoint":                      "/v1/company-candidates/search",
		"supported_sorts":               []string{"score_desc", "score_asc", "latest", "salary_asc", "salary_desc"},
		"max_results":                   maxMarketplaceRows,
		"latest_report_semantics":       "assessment_reports.created_at desc, assessment_reports.id desc per candidate",
		"skill_filtering":               "sql-side pre-filter (skill_tags first, candidate_skills fallback); go-side definitive filter",
	})
}

func (s *server) handleSearch(w http.ResponseWriter, r *http.Request) {
	var payload searchRequest
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON body")
		return
	}
	payload.normalize()
	if payload.CompanyID == "" {
		writeError(w, http.StatusUnprocessableEntity, "company_id is required")
		return
	}
	if payload.Sort != "" && !allowedSorts[payload.Sort] {
		writeError(w, http.StatusUnprocessableEntity, "unsupported sort")
		return
	}
	if payload.Sort == "" {
		payload.Sort = "score_desc"
	}

	items, err := s.search(r.Context(), payload)
	if err != nil {
		var apiErr providerError
		if errors.As(err, &apiErr) {
			writeError(w, apiErr.status, apiErr.detail)
			return
		}
		writeError(w, http.StatusBadGateway, err.Error())
		return
	}
	writeJSON(w, http.StatusOK, items)
}

func (r *searchRequest) normalize() {
	r.CompanyID = strings.TrimSpace(r.CompanyID)
	r.Q = strings.TrimSpace(r.Q)
	r.Role = strings.TrimSpace(r.Role)
	r.Recommendation = strings.TrimSpace(r.Recommendation)
	r.HireOutcome = strings.TrimSpace(r.HireOutcome)
	r.ShortlistID = strings.TrimSpace(r.ShortlistID)
	r.Sort = strings.TrimSpace(r.Sort)
	normalizedSkills := make([]string, 0, len(r.Skills))
	for _, skill := range r.Skills {
		value := normalizeSkillName(skill)
		if value != "" {
			normalizedSkills = append(normalizedSkills, value)
		}
	}
	r.Skills = normalizedSkills
}

func (s *server) searchCandidates(ctx context.Context, req searchRequest) ([]candidateItem, error) {
	if s.db == nil {
		return nil, providerError{status: http.StatusServiceUnavailable, detail: "database is not configured"}
	}

	query, args := buildMarketplaceQuery(req)
	rows, err := s.db.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	items := make([]candidateItem, 0)
	candidateIDs := make([]string, 0)
	itemIndexByCandidateID := map[string]int{}
	for rows.Next() {
		item, err := scanCandidateItem(rows)
		if err != nil {
			return nil, err
		}
		items = append(items, item)
		candidateIDs = append(candidateIDs, item.CandidateID)
		itemIndexByCandidateID[item.CandidateID] = len(items) - 1
	}
	if err := rows.Err(); err != nil {
		return nil, err
	}
	if len(items) == 0 {
		return []candidateItem{}, nil
	}

	shortlists, err := s.loadShortlists(ctx, req.CompanyID, candidateIDs)
	if err != nil {
		return nil, err
	}
	for candidateID, memberships := range shortlists {
		if index, ok := itemIndexByCandidateID[candidateID]; ok {
			items[index].Shortlists = memberships
		}
	}

	_, skillTags, err := s.loadCandidateSkills(ctx, candidateIDs)
	if err != nil {
		return nil, err
	}
	for candidateID, index := range itemIndexByCandidateID {
		items[index].aggregatedSkillTags = skillTags[candidateID]
		if items[index].reportSkillTagsEmpty && len(items[index].aggregatedSkillTags) > 0 {
			items[index].SkillTags = items[index].aggregatedSkillTags
		}
	}

	return filterBySkills(items, req.Skills), nil
}

func buildMarketplaceQuery(req searchRequest) (string, []any) {
	args := []any{req.CompanyID}
	nextArg := func(value any) string {
		args = append(args, value)
		return "$" + strconv.Itoa(len(args))
	}

	var filters []string
	if req.Q != "" {
		placeholder := nextArg("%" + req.Q + "%")
		filters = append(filters, "(c.full_name ILIKE "+placeholder+" OR u.email ILIKE "+placeholder+")")
	}
	if req.Role != "" {
		filters = append(filters, "i.target_role = "+nextArg(req.Role))
	}
	if req.Recommendation != "" {
		filters = append(filters, "ar.hiring_recommendation = "+nextArg(req.Recommendation))
	}
	if req.MinScore != nil {
		filters = append(filters, "ar.overall_score IS NOT NULL")
		filters = append(filters, "ar.overall_score >= "+nextArg(*req.MinScore))
	}
	if req.HireOutcome != "" {
		filters = append(filters, "ho.outcome = "+nextArg(req.HireOutcome))
	}
	if req.ShortlistID != "" {
		filters = append(filters, `EXISTS (
			SELECT 1
			FROM company_shortlist_candidates csc
			JOIN company_shortlists cs ON csc.shortlist_id = cs.id
			WHERE csc.candidate_id = c.id
			  AND csc.shortlist_id = `+nextArg(req.ShortlistID)+`::uuid
			  AND cs.company_id = $1::uuid
		)`)
	}
	if req.SalaryMin != nil || req.SalaryMax != nil {
		filters = append(filters, "COALESCE(c.salary_min, c.salary_max) IS NOT NULL")
		filters = append(filters, "COALESCE(c.salary_max, c.salary_min) IS NOT NULL")
		if req.SalaryMin != nil {
			filters = append(filters, "COALESCE(c.salary_max, c.salary_min) >= "+nextArg(*req.SalaryMin))
		}
		if req.SalaryMax != nil {
			filters = append(filters, "COALESCE(c.salary_min, c.salary_max) <= "+nextArg(*req.SalaryMax))
		}
	}
	if len(req.Skills) > 0 {
		// Pre-filter by skills in SQL using the same fallback logic as Go/Python:
		// - when report skill_tags is non-empty: require all skills to appear in skill_tags JSON
		// - when report skill_tags is empty: require all skills to appear in candidate_skills rows
		// Go-side filterBySkills remains the definitive gate; this clause reduces the result set size.
		p := nextArg(req.Skills)
		filters = append(filters, `(
			CASE
				WHEN jsonb_array_length(COALESCE(ar.skill_tags, '[]'::jsonb)) > 0 THEN
					NOT EXISTS (
						SELECT 1 FROM unnest(`+p+`::text[]) AS rs(required_skill)
						WHERE NOT EXISTS (
							SELECT 1 FROM jsonb_array_elements(ar.skill_tags) AS st
							WHERE lower(trim(st->>'skill')) = rs.required_skill
						)
					)
				ELSE
					NOT EXISTS (
						SELECT 1 FROM unnest(`+p+`::text[]) AS rs(required_skill)
						WHERE NOT EXISTS (
							SELECT 1 FROM candidate_skills cs_filter
							WHERE cs_filter.candidate_id = c.id
							  AND lower(trim(cs_filter.skill_name)) = rs.required_skill
						)
					)
			END
		)`)
	}

	where := "WHERE lrr.rank = 1"
	if len(filters) > 0 {
		where += " AND " + strings.Join(filters, " AND ")
	}

	limitArg := nextArg(maxMarketplaceRows)
	return `
WITH latest_report_rank AS (
	SELECT
		ar.id AS report_id,
		ROW_NUMBER() OVER (
			PARTITION BY ar.candidate_id
			ORDER BY ar.created_at DESC, ar.id DESC
		) AS rank
	FROM assessment_reports ar
	JOIN interviews i ON ar.interview_id = i.id
	JOIN candidates c ON ar.candidate_id = c.id
	WHERE i.company_assessment_id IS NULL
	  AND c.profile_visibility = 'marketplace'
)
SELECT
	ar.id::text,
	ar.candidate_id::text,
	c.full_name,
	u.email,
	i.target_role,
	ar.overall_score,
	ar.hiring_recommendation,
	ar.interview_summary,
	i.completed_at,
	c.salary_min,
	c.salary_max,
	COALESCE(c.salary_currency, 'USD'),
	ho.outcome,
	COALESCE(ar.skill_tags::text, '[]'),
	ar.cheat_risk_score,
	COALESCE(ar.red_flags::text, '[]')
FROM assessment_reports ar
JOIN latest_report_rank lrr ON ar.id = lrr.report_id
JOIN interviews i ON ar.interview_id = i.id
JOIN candidates c ON ar.candidate_id = c.id
JOIN users u ON c.user_id = u.id
LEFT JOIN hire_outcomes ho ON ho.company_id = $1::uuid AND ho.candidate_id = c.id
` + where + `
` + orderByClause(req.Sort) + `
LIMIT ` + limitArg, args
}

func orderByClause(sort string) string {
	switch sort {
	case "latest":
		return "ORDER BY i.completed_at DESC, ar.created_at DESC"
	case "score_asc":
		return "ORDER BY ar.overall_score IS NULL, ar.overall_score ASC"
	case "salary_asc":
		return "ORDER BY (c.salary_min IS NULL AND c.salary_max IS NULL), COALESCE(c.salary_min, c.salary_max) ASC"
	case "salary_desc":
		return "ORDER BY COALESCE(c.salary_max, c.salary_min, -1) DESC"
	default:
		return "ORDER BY COALESCE(ar.overall_score, -1) DESC"
	}
}

type rowScanner interface {
	Scan(dest ...any) error
}

func scanCandidateItem(row rowScanner) (candidateItem, error) {
	var item candidateItem
	var overall sql.NullFloat64
	var summary sql.NullString
	var completedAt sql.NullTime
	var salaryMin sql.NullInt64
	var salaryMax sql.NullInt64
	var hireOutcome sql.NullString
	var skillTagsRaw string
	var cheatRisk sql.NullFloat64
	var redFlagsRaw string

	if err := row.Scan(
		&item.ReportID,
		&item.CandidateID,
		&item.FullName,
		&item.Email,
		&item.TargetRole,
		&overall,
		&item.HiringRecommendation,
		&summary,
		&completedAt,
		&salaryMin,
		&salaryMax,
		&item.SalaryCurrency,
		&hireOutcome,
		&skillTagsRaw,
		&cheatRisk,
		&redFlagsRaw,
	); err != nil {
		return candidateItem{}, err
	}

	item.OverallScore = nullableFloat(overall)
	item.InterviewSummary = nullableString(summary)
	item.CompletedAt = nullableTime(completedAt)
	item.SalaryMin = nullableInt(salaryMin)
	item.SalaryMax = nullableInt(salaryMax)
	item.HireOutcome = nullableString(hireOutcome)
	item.CheatRiskScore = nullableFloat(cheatRisk)
	item.SkillTags = parseJSONList(skillTagsRaw)
	item.reportSkillTagsEmpty = len(item.SkillTags) == 0
	item.RedFlagCount = len(parseJSONList(redFlagsRaw))
	item.Shortlists = []shortlistMembership{}
	return item, nil
}

func (s *server) loadShortlists(ctx context.Context, companyID string, candidateIDs []string) (map[string][]shortlistMembership, error) {
	query, args := inQuery(`
SELECT csc.candidate_id::text, cs.id::text, cs.name
FROM company_shortlist_candidates csc
JOIN company_shortlists cs ON csc.shortlist_id = cs.id
WHERE cs.company_id = $1::uuid AND csc.candidate_id IN (`, companyID, candidateIDs)
	rows, err := s.db.Query(ctx, query, args...)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	result := map[string][]shortlistMembership{}
	for rows.Next() {
		var candidateID string
		var membership shortlistMembership
		if err := rows.Scan(&candidateID, &membership.ShortlistID, &membership.Name); err != nil {
			return nil, err
		}
		result[candidateID] = append(result[candidateID], membership)
	}
	return result, rows.Err()
}

func (s *server) loadCandidateSkills(ctx context.Context, candidateIDs []string) (map[string]map[string]bool, map[string][]map[string]any, error) {
	query, args := inQuery(`
SELECT candidate_id::text, skill_name, proficiency
FROM candidate_skills
WHERE candidate_id IN (`, nil, candidateIDs)
	query += " ORDER BY created_at DESC"
	rows, err := s.db.Query(ctx, query, args...)
	if err != nil {
		return nil, nil, err
	}
	defer rows.Close()

	bestByCandidate := map[string]map[string]map[string]any{}
	for rows.Next() {
		var candidateID string
		var skillName string
		var proficiency string
		if err := rows.Scan(&candidateID, &skillName, &proficiency); err != nil {
			return nil, nil, err
		}
		normalized := normalizeSkillName(skillName)
		if normalized == "" {
			continue
		}
		if bestByCandidate[candidateID] == nil {
			bestByCandidate[candidateID] = map[string]map[string]any{}
		}
		existing := bestByCandidate[candidateID][normalized]
		if existing == nil || proficiencyRank(proficiency) > proficiencyRank(fmt.Sprint(existing["proficiency"])) {
			bestByCandidate[candidateID][normalized] = map[string]any{
				"skill":          skillName,
				"proficiency":    proficiency,
				"mentions_count": 1,
			}
		}
	}
	if err := rows.Err(); err != nil {
		return nil, nil, err
	}

	nameMap := map[string]map[string]bool{}
	tagMap := map[string][]map[string]any{}
	for candidateID, skills := range bestByCandidate {
		nameMap[candidateID] = map[string]bool{}
		for normalized := range skills {
			nameMap[candidateID][normalized] = true
			tagMap[candidateID] = append(tagMap[candidateID], skills[normalized])
		}
		sort.Slice(tagMap[candidateID], func(i, j int) bool {
			left := tagMap[candidateID][i]
			right := tagMap[candidateID][j]
			leftRank := proficiencyRank(fmt.Sprint(left["proficiency"]))
			rightRank := proficiencyRank(fmt.Sprint(right["proficiency"]))
			if leftRank != rightRank {
				return leftRank > rightRank
			}
			return strings.ToLower(fmt.Sprint(left["skill"])) < strings.ToLower(fmt.Sprint(right["skill"]))
		})
	}
	return nameMap, tagMap, nil
}

func inQuery(prefix string, firstArg any, ids []string) (string, []any) {
	args := []any{}
	nextIndex := 1
	if firstArg != nil {
		args = append(args, firstArg)
		nextIndex = 2
	}
	placeholders := make([]string, 0, len(ids))
	for _, id := range ids {
		args = append(args, id)
		placeholders = append(placeholders, "$"+strconv.Itoa(nextIndex)+"::uuid")
		nextIndex++
	}
	return prefix + strings.Join(placeholders, ",") + ")", args
}

func filterBySkills(items []candidateItem, skills []string) []candidateItem {
	required := map[string]bool{}
	for _, skill := range skills {
		if normalized := normalizeSkillName(skill); normalized != "" {
			required[normalized] = true
		}
	}
	if len(required) == 0 {
		return items
	}

	filtered := make([]candidateItem, 0, len(items))
	for _, item := range items {
		skillNames := skillNamesFromTags(item.SkillTags)
		if containsAllSkills(skillNames, required) {
			filtered = append(filtered, item)
		}
	}
	return filtered
}

func skillNamesFromTags(tags []map[string]any) map[string]bool {
	names := map[string]bool{}
	for _, tag := range tags {
		if normalized := normalizeSkillName(fmt.Sprint(tag["skill"])); normalized != "" {
			names[normalized] = true
		}
	}
	return names
}

func containsAllSkills(actual map[string]bool, required map[string]bool) bool {
	for skill := range required {
		if !actual[skill] {
			return false
		}
	}
	return true
}

func parseJSONList(raw string) []map[string]any {
	var items []map[string]any
	if err := json.Unmarshal([]byte(raw), &items); err != nil {
		return []map[string]any{}
	}
	if items == nil {
		return []map[string]any{}
	}
	return items
}

func nullableFloat(value sql.NullFloat64) *float64 {
	if !value.Valid {
		return nil
	}
	result := value.Float64
	return &result
}

func nullableInt(value sql.NullInt64) *int {
	if !value.Valid {
		return nil
	}
	result := int(value.Int64)
	return &result
}

func nullableString(value sql.NullString) *string {
	if !value.Valid {
		return nil
	}
	result := value.String
	return &result
}

func nullableTime(value sql.NullTime) *time.Time {
	if !value.Valid {
		return nil
	}
	result := value.Time
	return &result
}

func normalizeSkillName(value string) string {
	return strings.ToLower(strings.TrimSpace(value))
}

func proficiencyRank(value string) int {
	switch strings.ToLower(strings.TrimSpace(value)) {
	case "expert":
		return 3
	case "advanced":
		return 2
	case "intermediate":
		return 1
	default:
		return 0
	}
}

func normalizeDatabaseURL(value string) string {
	normalized := strings.TrimSpace(value)
	normalized = strings.Replace(normalized, "postgresql+asyncpg://", "postgres://", 1)
	normalized = strings.Replace(normalized, "postgres+asyncpg://", "postgres://", 1)
	return normalized
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
