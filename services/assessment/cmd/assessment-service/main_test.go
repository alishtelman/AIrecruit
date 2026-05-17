package main

import (
	"encoding/json"
	"os"
	"path/filepath"
	"testing"
)

func TestComputeAggregatesParity(t *testing.T) {
	// Let's load the backend_engineer golden report and verify score parity!
	fixturePath := "/app/tests/fixtures/transcripts/backend_engineer_report.json"
	
	// If running outside Docker container during local test, fallback to relative path
	if _, err := os.Stat(fixturePath); os.IsNotExist(err) {
		fixturePath = filepath.Join("..", "..", "..", "..", "backend", "tests", "fixtures", "transcripts", "backend_engineer_report.json")
	}

	data, err := os.ReadFile(fixturePath)
	if err != nil {
		t.Fatalf("Failed to read golden fixture: %v", err)
	}

	var golden struct {
		OverallScore         float64           `json:"overall_score"`
		HardSkillsScore      float64           `json:"hard_skills_score"`
		SoftSkillsScore      float64           `json:"soft_skills_score"`
		CommunicationScore   float64           `json:"communication_score"`
		ProblemSolvingScore  float64           `json:"problem_solving_score"`
		CompetencyScores     []CompetencyScore `json:"competency_scores"`
	}

	if err := json.Unmarshal(data, &golden); err != nil {
		t.Fatalf("Failed to parse golden fixture: %v", err)
	}

	aggrs := computeAggregates(golden.CompetencyScores)

	expectedOverall := 7.0
	expectedHard := 7.5
	expectedSoft := 5.0
	expectedComm := 7.0
	expectedPS := 7.0

	if aggrs["overall_score"] != expectedOverall {
		t.Errorf("Parity mismatch: overall_score got %.1f, expected %.1f", aggrs["overall_score"], expectedOverall)
	}
	if aggrs["hard_skills_score"] != expectedHard {
		t.Errorf("Parity mismatch: hard_skills_score got %.1f, expected %.1f", aggrs["hard_skills_score"], expectedHard)
	}
	if aggrs["soft_skills_score"] != expectedSoft {
		t.Errorf("Parity mismatch: soft_skills_score got %.1f, expected %.1f", aggrs["soft_skills_score"], expectedSoft)
	}
	if aggrs["communication_score"] != expectedComm {
		t.Errorf("Parity mismatch: communication_score got %.1f, expected %.1f", aggrs["communication_score"], expectedComm)
	}
	if aggrs["problem_solving_score"] != expectedPS {
		t.Errorf("Parity mismatch: problem_solving_score got %.1f, expected %.1f", aggrs["problem_solving_score"], expectedPS)
	}
}

func TestGetCompetencies(t *testing.T) {
	comps := GetCompetencies("backend_engineer")
	if len(comps) != 10 {
		t.Errorf("Expected 10 competencies for backend_engineer, got %d", len(comps))
	}

	// Fallback check
	fallback := GetCompetencies("unknown_role")
	if len(fallback) != 10 {
		t.Errorf("Expected 10 competencies for fallback, got %d", len(fallback))
	}
}
