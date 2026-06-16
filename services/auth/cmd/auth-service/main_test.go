package main

import (
	"testing"
)

func TestPasswordHashingAndVerification(t *testing.T) {
	password := "SecretP@ssword123"

	hashed, err := hashPassword(password)
	if err != nil {
		t.Fatalf("Expected no error when hashing, got: %v", err)
	}

	if hashed == password {
		t.Error("Expected hashed password to be different from original password")
	}

	if !verifyPassword(password, hashed) {
		t.Error("Expected password to verify successfully against its hash")
	}

	if verifyPassword("wrong-password", hashed) {
		t.Error("Expected verifyPassword to return false for incorrect password")
	}
}

func TestNormalizeDatabaseURL(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{
			input:    "postgresql+asyncpg://user:pass@host:5432/db",
			expected: "postgres://user:pass@host:5432/db",
		},
		{
			input:    "postgres+asyncpg://user:pass@host:5432/db",
			expected: "postgres://user:pass@host:5432/db",
		},
		{
			input:    "postgres://user:pass@host:5432/db",
			expected: "postgres://user:pass@host:5432/db",
		},
		{
			input:    "  postgres://user:pass@host:5432/db  ",
			expected: "postgres://user:pass@host:5432/db",
		},
	}

	for _, tt := range tests {
		actual := normalizeDatabaseURL(tt.input)
		if actual != tt.expected {
			t.Errorf("For input %q, expected %q, got %q", tt.input, tt.expected, actual)
		}
	}
}

func TestCreateAccessToken(t *testing.T) {
	srv := &server{
		config: Config{
			SecretKey:                "test-secret",
			AccessTokenExpireMinutes: 60,
		},
	}

	subject := "user-uuid-1234"
	role := "candidate"

	tokenStr, err := srv.createAccessToken(subject, role)
	if err != nil {
		t.Fatalf("Expected no error creating access token, got: %v", err)
	}

	if tokenStr == "" {
		t.Error("Expected access token to not be empty")
	}
}

func TestNormalizeLoginAccountType(t *testing.T) {
	tests := []struct {
		input    string
		expected string
		ok       bool
	}{
		{input: "", expected: "", ok: false},
		{input: " candidate ", expected: "candidate", ok: true},
		{input: "company_admin", expected: "company", ok: true},
		{input: "company_member", expected: "company", ok: true},
		{input: "platform_admin", expected: "admin", ok: true},
		{input: "admin", expected: "admin", ok: true},
		{input: "recruiter", expected: "", ok: false},
	}

	for _, tt := range tests {
		actual, ok := normalizeLoginAccountType(tt.input)
		if actual != tt.expected || ok != tt.ok {
			t.Errorf("For input %q, expected (%q, %t), got (%q, %t)", tt.input, tt.expected, tt.ok, actual, ok)
		}
	}
}

func TestLoginAccountTypeAllowsRole(t *testing.T) {
	tests := []struct {
		accountType string
		role        string
		expected    bool
	}{
		{accountType: "", role: "candidate", expected: false},
		{accountType: "candidate", role: "candidate", expected: true},
		{accountType: "candidate", role: "company_admin", expected: false},
		{accountType: "candidate", role: "platform_admin", expected: false},
		{accountType: "company", role: "company_admin", expected: true},
		{accountType: "company", role: "company_member", expected: true},
		{accountType: "company", role: "candidate", expected: false},
		{accountType: "admin", role: "platform_admin", expected: true},
		{accountType: "admin", role: "company_admin", expected: false},
	}

	for _, tt := range tests {
		actual := loginAccountTypeAllowsRole(tt.accountType, tt.role)
		if actual != tt.expected {
			t.Errorf("Expected account type %q and role %q to be %t, got %t", tt.accountType, tt.role, tt.expected, actual)
		}
	}
}
