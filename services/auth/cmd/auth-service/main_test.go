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
