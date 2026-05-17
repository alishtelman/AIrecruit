package main

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"log"
	"math"
	"net/http"
	"os"
	"strings"
	"time"
)

const defaultListenAddr = ":8080"

type Message struct {
	Role    string `json:"role"`
	Content string `json:"content"`
}

type AssessRequest struct {
	TargetRole      string         `json:"target_role"`
	MessageHistory  []Message      `json:"message_history"`
	Language        string         `json:"language"`
	ModelOverride   string         `json:"model_override"`
	RuntimeSettings map[string]any `json:"runtime_settings"`
}

type QuestionAnalysis struct {
	QuestionNumber       int        `json:"question_number"`
	TargetedCompetencies []string   `json:"targeted_competencies"`
	AnswerQuality        float64    `json:"answer_quality"`
	Evidence             string     `json:"evidence"`
	SkillsMentioned      []SkillTag `json:"skills_mentioned"`
	RedFlags             []string   `json:"red_flags"`
	Specificity          string     `json:"specificity"`
	Depth                string     `json:"depth"`
	AiLikelihood         float64    `json:"ai_likelihood"`
}

type SkillTag struct {
	Skill       string `json:"skill"`
	Proficiency string `json:"proficiency"`
}

type CompetencyScore struct {
	Competency string  `json:"competency"`
	Category   string  `json:"category"`
	Score      float64 `json:"score"`
	Weight     float64 `json:"weight"`
	Evidence   string  `json:"evidence"`
	Reasoning  string  `json:"reasoning"`
}

type RedFlag struct {
	Flag     string `json:"flag"`
	Evidence string `json:"evidence"`
	Severity string `json:"severity"`
}

type AssessmentResult struct {
	OverallScore         float64            `json:"overall_score"`
	HardSkillsScore      float64            `json:"hard_skills_score"`
	SoftSkillsScore      float64            `json:"soft_skills_score"`
	CommunicationScore   float64            `json:"communication_score"`
	ProblemSolvingScore  float64            `json:"problem_solving_score"`
	Strengths            []string           `json:"strengths"`
	Weaknesses           []string           `json:"weaknesses"`
	Recommendations      []string           `json:"recommendations"`
	HiringRecommendation string             `json:"hiring_recommendation"`
	InterviewSummary     string             `json:"interview_summary"`
	ModelVersion         string             `json:"model_version"`
	CompetencyScores     []CompetencyScore  `json:"competency_scores"`
	PerQuestionAnalysis  []QuestionAnalysis `json:"per_question_analysis"`
	SkillTags            []SkillTag         `json:"skill_tags"`
	RedFlags             []RedFlag          `json:"red_flags"`
	ResponseConsistency  float64            `json:"response_consistency"`
}

type Pass2Output struct {
	CompetencyScores     []CompetencyScore `json:"competency_scores"`
	Strengths            []string          `json:"strengths"`
	Weaknesses           []string          `json:"weaknesses"`
	Recommendations      []string          `json:"recommendations"`
	HiringRecommendation string            `json:"hiring_recommendation"`
	InterviewSummary     string            `json:"interview_summary"`
	ResponseConsistency  float64           `json:"response_consistency"`
}

type LLMCompleteRequest struct {
	Provider       string         `json:"provider"`
	Model          string         `json:"model"`
	Messages       []Message      `json:"messages"`
	Temperature    float64        `json:"temperature"`
	MaxTokens      int            `json:"max_tokens"`
	TimeoutSeconds float64        `json:"timeout_seconds"`
	Tool           map[string]any `json:"tool"`
}

type LLMCompleteResponse struct {
	Text     string `json:"text"`
	Model    string `json:"model"`
	Provider string `json:"provider"`
}

type server struct {
	llmServiceURL string
	client        *http.Client
}

func main() {
	llmURL := envOrDefault("LLM_SERVICE_URL", "http://llm-service:8080")
	srv := &server{
		llmServiceURL: llmURL,
		client:        &http.Client{Timeout: 180 * time.Second},
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", func(w http.ResponseWriter, _ *http.Request) {
		writeJSON(w, http.StatusOK, map[string]string{"status": "ok", "service": "assessment-service"})
	})
	mux.HandleFunc("POST /v1/assess", srv.handleAssess)

	addr := envOrDefault("ASSESSMENT_SERVICE_ADDR", defaultListenAddr)
	log.Printf("Assessment service starting on %s...", addr)
	if err := http.ListenAndServe(addr, mux); err != nil {
		log.Fatalf("Failed to listen and serve: %v", err)
	}
}

func (s *server) handleAssess(w http.ResponseWriter, r *http.Request) {
	var payload AssessRequest
	if err := json.NewDecoder(r.Body).Decode(&payload); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid JSON body: "+err.Error())
		return
	}

	if payload.TargetRole == "" {
		writeError(w, http.StatusBadRequest, "target_role is required")
		return
	}

	log.Printf("Starting assessment for role: %s, history length: %d", payload.TargetRole, len(payload.MessageHistory))

	result, err := s.runAssessment(r.Context(), payload)
	if err != nil {
		log.Printf("Assessment failed: %v, falling back to deterministic mock assessment", err)
		result = s.generateMockAssessment(payload)
	}

	writeJSON(w, http.StatusOK, result)
}

func (s *server) runAssessment(ctx context.Context, req AssessRequest) (AssessmentResult, error) {
	roleLabel := getRoleLabel(req.TargetRole, req.Language)
	competencies := GetCompetencies(req.TargetRole)
	compRef := buildCompetencyRef(competencies)

	// Format transcript
	var sb strings.Builder
	for _, msg := range req.MessageHistory {
		sb.WriteString(fmt.Sprintf("%s: %s\n\n", strings.ToUpper(msg.Role), msg.Content))
	}
	transcript := sb.String()

	// 1. Pass 1: Question Analysis
	log.Println("Running Pass 1 (Question Analysis)...")
	pass1Questions, modelUsed, err := s.runPass1(ctx, roleLabel, transcript, compRef, req.Language, req.ModelOverride)
	if err != nil {
		return AssessmentResult{}, fmt.Errorf("pass 1 failed: %w", err)
	}

	// 2. Pass 2: Competency Assessment
	log.Println("Running Pass 2 (Competency Scoring)...")
	pass2Out, err := s.runPass2(ctx, roleLabel, transcript, compRef, pass1Questions, req.TargetRole, req.Language, req.ModelOverride)
	if err != nil {
		return AssessmentResult{}, fmt.Errorf("pass 2 failed: %w", err)
	}

	// 3. Compute deterministic aggregates
	aggrs := computeAggregates(pass2Out.CompetencyScores)

	// 4. Extract unique skills and red flags
	var skillTags []SkillTag
	skillSeen := make(map[string]bool)
	for _, q := range pass1Questions {
		for _, s := range q.SkillsMentioned {
			skillNorm := strings.ToLower(strings.TrimSpace(s.Skill))
			if skillNorm != "" && !skillSeen[skillNorm] {
				skillSeen[skillNorm] = true
				skillTags = append(skillTags, s)
			}
		}
	}

	var redFlags []RedFlag
	for _, q := range pass1Questions {
		for _, flag := range q.RedFlags {
			if strings.TrimSpace(flag) != "" {
				redFlags = append(redFlags, RedFlag{
					Flag:     flag,
					Evidence: q.Evidence,
					Severity: "medium",
				})
			}
		}
	}

	result := AssessmentResult{
		OverallScore:         aggrs["overall_score"],
		HardSkillsScore:      aggrs["hard_skills_score"],
		SoftSkillsScore:      aggrs["soft_skills_score"],
		CommunicationScore:   aggrs["communication_score"],
		ProblemSolvingScore:  aggrs["problem_solving_score"],
		Strengths:            pass2Out.Strengths,
		Weaknesses:           pass2Out.Weaknesses,
		Recommendations:      pass2Out.Recommendations,
		HiringRecommendation: pass2Out.HiringRecommendation,
		InterviewSummary:     pass2Out.InterviewSummary,
		ModelVersion:         modelUsed,
		CompetencyScores:     pass2Out.CompetencyScores,
		PerQuestionAnalysis:  pass1Questions,
		SkillTags:            skillTags,
		RedFlags:             redFlags,
		ResponseConsistency:  pass2Out.ResponseConsistency,
	}

	return result, nil
}

func (s *server) runPass1(ctx context.Context, roleLabel, transcript, compRef, language, modelOverride string) ([]QuestionAnalysis, string, error) {
	outputLang := "English"
	if language == "ru" {
		outputLang = "русском"
	}

	system := fmt.Sprintf(`Ты — строгий старший интервьюер, оценивающий кандидата на позицию «%s».
Твоя задача — объективно зафиксировать ФАКТЫ из ответов, не давать кандидату преимущество сомнения.

## Матрица компетенций
%s

## Задача
Для КАЖДОЙ пары вопрос-ответ определи:
1. Какие компетенции из матрицы этот вопрос оценивает
2. Качество ответа (1-10) — ТОЛЬКО по фактическому содержанию
3. Конкретные доказательства из ответа (прямые цитаты или специфические факты)
4. Технологии/навыки с ЛИЧНЫМ опытом использования
5. Красные флаги (противоречия, уход от вопроса, повторения, фабрикации)
6. Конкретность (high/medium/low) и глубина (expert/strong/adequate/surface/none)
7. Вероятность AI-генерации (ai_likelihood 0.0-1.0)

## ЖЁСТКИЕ ПРАВИЛА ОЦЕНКИ ANSWER_QUALITY — ОБЯЗАТЕЛЬНЫ

КОРОТКИЙ ОТВЕТ (<10 слов):
- answer_quality ОБЯЗАН быть ≤ 3
- depth = 'surface' или 'none'
- specificity = 'low'
- добавь в red_flags: 'answer too short'

ОБЩИЙ ОТВЕТ (нет конкретного примера, нет реального проекта):
- answer_quality ОБЯЗАН быть ≤ 5
- specificity = 'low'
- добавь в red_flags: 'answer generic — no real-world example'

НЕТ ОБЪЯСНЕНИЯ 'КАК' И 'ПОЧЕМУ':
- depth = 'surface' (максимум 'adequate' если есть хоть что-то)
- answer_quality снижается на 1-2 пункта

КОНКРЕТНЫЙ ПРАКТИЧЕСКИЙ ОТВЕТ БЕЗ ЦИФР:
- если кандидат ясно описал, что именно делал, как работало решение и какие trade-offs учитывал,
  такой ответ МОЖЕТ получить 7-8 даже без численных метрик
- не штрафуй сильный практический ответ только за отсутствие процентов или p95

УКЛОНЧИВЫЙ ОТВЕТ (не отвечает на вопрос):
- answer_quality ОБЯЗАН быть ≤ 3
- добавь в red_flags: 'evasive — question avoided'

П ПОВТОРЯЮЩИЙСЯ ОТВЕТ (то же самое что в предыдущих вопросах):
- добавь в red_flags: 'answer repeated'
- answer_quality снижается на 1-2 пункта

АБСОЛЮТНЫЕ ЗАПРЕТЫ:
- НЕ давай answer_quality > 3 для ответов короче 10 слов
- НЕ давай answer_quality > 5 для ответов без единого конкретного примера
- НЕ давай answer_quality > 8 без конкретного механизма, личного вклада или trade-off рассуждения
- НЕ записывай в skills_mentioned широкие термины (api, backend, database) без личного опыта

Шкала answer_quality: 1-3 = нет ответа/слишком коротко/уклонение, 4-5 = поверхностно/без примеров, 5-6 = рабочие знания с примерами, 7-8 = конкретика + trade-offs + результаты, 9-10 = экспертное мышление.
Большинство ответов реальных кандидатов: 4-6. Не завышай.

AI-генерация признаки: буллет-пойнты без просьбы, фразы 'Certainly/Great question/In conclusion', идеальное покрытие всех аспектов без личных примеров, академический тон, ответ на незаданные вопросы. Живой человек: личные примеры, неполные мысли, специфические детали, неформальный язык.

ВАЖНО: все свободные текстовые поля ответа (evidence, red_flags) верни на %s. Enum-значения (specificity, depth, proficiency) оставь в допустимом формате schema.`, roleLabel, compRef, outputLang)

	var toolMap map[string]any
	if err := json.Unmarshal([]byte(QuestionAnalysisToolJSON), &toolMap); err != nil {
		return nil, "", err
	}

	model := "deepseek/deepseek-chat"
	if modelOverride != "" {
		model = modelOverride
	}

	llmReq := LLMCompleteRequest{
		Provider:       "openrouter",
		Model:          model,
		Messages: []Message{
			{Role: "system", Content: system},
			{Role: "user", Content: fmt.Sprintf("Транскрипт:\n\n%s", transcript)},
		},
		Temperature:    0.2,
		MaxTokens:      2048,
		TimeoutSeconds: 120,
		Tool:           toolMap,
	}

	resp, err := s.callLLM(ctx, llmReq)
	if err != nil {
		return nil, "", err
	}

	var parsed struct {
		Questions []QuestionAnalysis `json:"questions"`
	}
	if err := json.Unmarshal([]byte(resp.Text), &parsed); err != nil {
		// Clean json markers if present
		cleaned := cleanJSONText(resp.Text)
		if err := json.Unmarshal([]byte(cleaned), &parsed); err != nil {
			return nil, "", fmt.Errorf("failed to parse pass 1 response JSON: %w (raw response: %s)", err, resp.Text)
		}
	}

	return parsed.Questions, resp.Model, nil
}

func (s *server) runPass2(ctx context.Context, roleLabel, transcript, compRef string, pass1Questions []QuestionAnalysis, targetRole, language, modelOverride string) (Pass2Output, error) {
	pass1SummaryBytes, _ := json.MarshalIndent(map[string]any{"questions": pass1Questions}, "", "  ")
	pass1Summary := string(pass1SummaryBytes)

	categoriesSeen := make(map[string]bool)
	for _, c := range GetCompetencies(targetRole) {
		categoriesSeen[c.Category] = true
	}
	var categories []string
	for cat := range categoriesSeen {
		categories = append(categories, cat)
	}

	calibrationBlock := BuildCalibrationPrompt(categories)
	outputLang := "English"
	if language == "ru" {
		outputLang = "русском"
	}

	system := fmt.Sprintf(`Ты — строгий старший интервьюер, оценивающий кандидата на позицию «%s».
Ты оцениваешь как скептик: любое утверждение без доказательства не засчитывается.

## Матрица компетенций
%s

%s

## Задача
На основе транскрипта и анализа вопросов (Pass 1):
1. Выставь балл (1-10) для КАЖДОЙ компетенции, строго следуя BARS выше
2. evidence: ОБЯЗАТЕЛЬНО содержит прямую цитату или конкретный факт из транскрипта
3. reasoning: объясняет ПОЧЕМУ именно этот балл (не просто пересказ ответа)
4. 3-5 strengths и 2-4 weaknesses с конкретными примерами из ответов
5. response_consistency (0-10): насколько ответы не противоречат друг другу
6. red_flags с severity для каждого выявленного сигнала
7. hiring_recommendation: strong_yes (≥8.5), yes (7.0–8.4), maybe (5.5–6.9), no (<5.5)

## ЖЁСТКИЕ ПРАВИЛА SCORING — НЕЛЬЗЯ НАРУШАТЬ

НЕТ ДОКАЗАТЕЛЬСТВ = НИЗКИЙ БАЛЛ:
- Если не можешь процитировать конкретный пример из транскрипта → score ≤ 4
- evidence = пересказ/общие слова → score ≤ 5
- Каждый score выше 5 ТРЕБУЕТ реальной цитаты с конкретикой

ЖЁСТКИЕ ПОТОЛКИ:
- Score > 7: требует метрик, trade-offs И прямых цитат
- Score > 6: требует хотя бы одного реального примера с объяснением КАК/ПОЧЕМУ
- Score > 5: требует упоминания конкретной технологии с личным опытом
- Score > 4: требует хотя бы базового понимания своими словами

ПРАВИЛО КРИТИЧЕСКОЙ СЛАБОСТИ:
- Если ≥1 компетенция scored ≤ 4 → overall взвешенное среднее ДОЛЖНО быть ≤ 6
- Если ≥2 компетенции scored ≤ 3 → overall ДОЛЖНО быть ≤ 5
- hiring_recommendation 'yes' или 'strong_yes' ЗАПРЕЩЕНО если любая ключевая компетенция ≤ 4

PHILOSOPHY:
- Слабые кандидаты: 3-5. Средние: 5-6. Хорошие: 7-8. Исключительные: 9-10.
- При сомнении — снижай. Цена false-positive выше чем false-negative.
- Не давай credit за намерения — только за доказанные знания и опыт.

ВАЖНО: все свободные текстовые поля (evidence, reasoning, strengths, weaknesses, recommendations, interview_summary, red_flags.flag, red_flags.evidence) верни на %s. Enum-значения и числовые поля не переводить.`, roleLabel, compRef, calibrationBlock, outputLang)

	var toolMap map[string]any
	if err := json.Unmarshal([]byte(CompetencyAssessmentToolJSON), &toolMap); err != nil {
		return Pass2Output{}, err
	}

	model := "deepseek/deepseek-chat"
	if modelOverride != "" {
		model = modelOverride
	}

	userContent := fmt.Sprintf("## Транскрипт\n%s\n\n## Анализ вопросов (Pass 1)\n%s", transcript, pass1Summary)

	llmReq := LLMCompleteRequest{
		Provider:       "openrouter",
		Model:          model,
		Messages: []Message{
			{Role: "system", Content: system},
			{Role: "user", Content: userContent},
		},
		Temperature:    0.2,
		MaxTokens:      2048,
		TimeoutSeconds: 120,
		Tool:           toolMap,
	}

	resp, err := s.callLLM(ctx, llmReq)
	if err != nil {
		return Pass2Output{}, err
	}

	var parsed Pass2Output
	if err := json.Unmarshal([]byte(resp.Text), &parsed); err != nil {
		cleaned := cleanJSONText(resp.Text)
		if err := json.Unmarshal([]byte(cleaned), &parsed); err != nil {
			return Pass2Output{}, fmt.Errorf("failed to parse pass 2 response JSON: %w (raw response: %s)", err, resp.Text)
		}
	}

	return parsed, nil
}

func (s *server) callLLM(ctx context.Context, req LLMCompleteRequest) (LLMCompleteResponse, error) {
	body, err := json.Marshal(req)
	if err != nil {
		return LLMCompleteResponse{}, err
	}

	httpReq, err := http.NewRequestWithContext(ctx, http.MethodPost, s.llmServiceURL+"/v1/complete", bytes.NewReader(body))
	if err != nil {
		return LLMCompleteResponse{}, err
	}
	httpReq.Header.Set("Content-Type", "application/json")

	resp, err := s.client.Do(httpReq)
	if err != nil {
		return LLMCompleteResponse{}, err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		raw, _ := io.ReadAll(resp.Body)
		return LLMCompleteResponse{}, fmt.Errorf("llm-service returned status %d: %s", resp.StatusCode, string(raw))
	}

	var completion LLMCompleteResponse
	if err := json.NewDecoder(resp.Body).Decode(&completion); err != nil {
		return LLMCompleteResponse{}, err
	}

	return completion, nil
}

func computeAggregates(scores []CompetencyScore) map[string]float64 {
	catScores := make(map[string][]struct{ s, w float64 })
	totalWeighted := 0.0
	totalWeight := 0.0

	for _, cs := range scores {
		catScores[cs.Category] = append(catScores[cs.Category], struct{ s, w float64 }{cs.Score, cs.Weight})
		totalWeighted += cs.Score * cs.Weight
		totalWeight += cs.Weight
	}

	weightedAvg := func(pairs []struct{ s, w float64 }) float64 {
		tw := 0.0
		for _, p := range pairs {
			tw += p.w
		}
		if tw == 0 {
			return 0.0
		}
		sum := 0.0
		for _, p := range pairs {
			sum += p.s * p.w
		}
		return sum / tw
	}

	techCore := catScores["technical_core"]
	techBreadth := catScores["technical_breadth"]
	hard := weightedAvg(append(techCore, techBreadth...))

	soft := weightedAvg(catScores["behavioral"])
	comm := weightedAvg(catScores["communication"])
	ps := weightedAvg(catScores["problem_solving"])

	overall := 0.0
	if totalWeight > 0 {
		overall = totalWeighted / totalWeight
	}

	roundTo1 := func(v float64) float64 {
		return math.Round(v*10) / 10
	}

	return map[string]float64{
		"overall_score":         roundTo1(overall),
		"hard_skills_score":      roundTo1(hard),
		"soft_skills_score":      roundTo1(soft),
		"communication_score":   roundTo1(comm),
		"problem_solving_score": roundTo1(ps),
	}
}

func (s *server) generateMockAssessment(req AssessRequest) AssessmentResult {
	competencies := GetCompetencies(req.TargetRole)
	var scores []CompetencyScore
	for _, c := range competencies {
		scores = append(scores, CompetencyScore{
			Competency: c.Name,
			Category:   c.Category,
			Score:      6.0,
			Weight:     c.Weight,
			Evidence:   "Mock evidence from answers",
			Reasoning:  "Mock reasoning",
		})
	}
	aggrs := computeAggregates(scores)

	return AssessmentResult{
		OverallScore:         aggrs["overall_score"],
		HardSkillsScore:      aggrs["hard_skills_score"],
		SoftSkillsScore:      aggrs["soft_skills_score"],
		CommunicationScore:   aggrs["communication_score"],
		ProblemSolvingScore:  aggrs["problem_solving_score"],
		Strengths:            []string{"Mock strength 1", "Mock strength 2"},
		Weaknesses:           []string{"Mock weakness 1"},
		Recommendations:      []string{"Mock recommendation 1"},
		HiringRecommendation: "yes",
		InterviewSummary:     "Mock interview summary.",
		ModelVersion:         "mock-model",
		CompetencyScores:     scores,
		PerQuestionAnalysis:  []QuestionAnalysis{},
		SkillTags:            []SkillTag{},
		RedFlags:             []RedFlag{},
		ResponseConsistency:  8.0,
	}
}

func buildCompetencyRef(competencies []Competency) string {
	var sb strings.Builder
	for _, c := range competencies {
		sb.WriteString(fmt.Sprintf("- %s (%s, вес %.2f): %s\n", c.Name, c.Category, c.Weight, c.Description))
	}
	return sb.String()
}

func getRoleLabel(role, lang string) string {
	labels := map[string]map[string]string{
		"ru": {
			"backend_engineer":  "Backend-разработчик",
			"frontend_engineer": "Frontend-разработчик",
			"qa_engineer":       "QA-инженер",
			"devops_engineer":   "DevOps-инженер",
			"data_scientist":    "Data Scientist",
			"product_manager":   "Продакт-менеджер",
			"mobile_engineer":   "Mobile-разработчик",
			"designer":          "UX/UI Дизайнер",
		},
		"en": {
			"backend_engineer":  "Backend Engineer",
			"frontend_engineer": "Frontend Engineer",
			"qa_engineer":       "QA Engineer",
			"devops_engineer":   "DevOps Engineer",
			"data_scientist":    "Data Scientist",
			"product_manager":   "Product Manager",
			"mobile_engineer":   "Mobile Engineer",
			"designer":          "UX/UI Designer",
		},
	}
	lMap, ok := labels[lang]
	if !ok {
		lMap = labels["ru"]
	}
	if label, ok := lMap[role]; ok {
		return label
	}
	return role
}

func cleanJSONText(text string) string {
	text = strings.TrimSpace(text)
	if strings.HasPrefix(text, "```json") {
		text = strings.TrimPrefix(text, "```json")
		if strings.HasSuffix(text, "```") {
			text = strings.TrimSuffix(text, "```")
		}
	} else if strings.HasPrefix(text, "```") {
		text = strings.TrimPrefix(text, "```")
		if strings.HasSuffix(text, "```") {
			text = strings.TrimSuffix(text, "```")
		}
	}
	return strings.TrimSpace(text)
}

func envOrDefault(key string, fallback string) string {
	value := strings.TrimSpace(os.Getenv(key))
	if value == "" {
		return fallback
	}
	return value
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]any{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}

const QuestionAnalysisToolJSON = `{
    "type": "function",
    "function": {
        "name": "submit_question_analysis",
        "description": "Submit per-question analysis for the interview transcript.",
        "parameters": {
            "type": "object",
            "properties": {
                "questions": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "question_number": {"type": "integer"},
                            "targeted_competencies": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Competency names this Q&A evaluates"
                            },
                            "answer_quality": {
                                "type": "number",
                                "description": "Score 1-10 for answer quality"
                            },
                            "evidence": {
                                "type": "string",
                                "description": "Concrete evidence from the answer (quotes, examples)"
                            },
                            "skills_mentioned": {
                                "type": "array",
                                "items": {
                                    "type": "object",
                                    "properties": {
                                        "skill": {"type": "string"},
                                        "proficiency": {
                                            "type": "string",
                                            "enum": ["beginner", "intermediate", "advanced", "expert"]
                                        }
                                    },
                                    "required": ["skill", "proficiency"]
                                },
                                "description": "ONLY explicit, demonstrated skills from the answer."
                            },
                            "red_flags": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Any red flags detected (contradictions, fabrication, etc.)"
                            },
                            "specificity": {
                                "type": "string",
                                "enum": ["high", "medium", "low"]
                            },
                            "depth": {
                                "type": "string",
                                "enum": ["expert", "strong", "adequate", "surface", "none"]
                            },
                            "ai_likelihood": {
                                "type": "number",
                                "description": "Probability 0.0-1.0 that this answer was AI-generated."
                            }
                        },
                        "required": [
                            "question_number", "targeted_competencies",
                            "answer_quality", "evidence", "skills_mentioned",
                            "red_flags", "specificity", "depth", "ai_likelihood"
                        ]
                    }
                }
            },
            "required": ["questions"]
        }
    }
}`

const CompetencyAssessmentToolJSON = `{
    "type": "function",
    "function": {
        "name": "submit_competency_assessment",
        "description": "Submit competency-based assessment using evidence from question analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "competency_scores": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "competency": {"type": "string"},
                            "category": {"type": "string"},
                            "score": {"type": "number", "description": "1-10"},
                            "weight": {"type": "number"},
                            "evidence": {"type": "string"},
                            "reasoning": {"type": "string"}
                        },
                        "required": ["competency", "category", "score", "weight", "evidence", "reasoning"]
                    }
                },
                "strengths": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "weaknesses": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "recommendations": {
                    "type": "array",
                    "items": {"type": "string"}
                },
                "hiring_recommendation": {
                    "type": "string",
                    "enum": ["strong_yes", "yes", "maybe", "no"]
                },
                "interview_summary": {
                    "type": "string"
                },
                "response_consistency": {
                    "type": "number"
                }
            },
            "required": [
                "competency_scores", "strengths", "weaknesses", "recommendations",
                "hiring_recommendation", "interview_summary", "response_consistency"
            ]
        }
    }
}`
