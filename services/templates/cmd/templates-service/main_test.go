package main

import (
	"testing"
)

func TestNormalizeDatabaseURL(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{
			input:    "postgresql+asyncpg://user:pass@localhost:5432/db",
			expected: "postgres://user:pass@localhost:5432/db",
		},
		{
			input:    "postgres+asyncpg://user:pass@localhost:5432/db",
			expected: "postgres://user:pass@localhost:5432/db",
		},
		{
			input:    "postgres://user:pass@localhost:5432/db",
			expected: "postgres://user:pass@localhost:5432/db",
		},
	}

	for _, tc := range tests {
		got := normalizeDatabaseURL(tc.input)
		if got != tc.expected {
			t.Errorf("normalizeDatabaseURL(%q) = %q; want %q", tc.input, got, tc.expected)
		}
	}
}

func TestMaskConnString(t *testing.T) {
	tests := []struct {
		input    string
		expected string
	}{
		{
			input:    "postgres://user:pass@localhost:5432/db",
			expected: "postgres://***:***@localhost:5432/db",
		},
		{
			input:    "invalid-url",
			expected: "[redacted]",
		},
	}

	for _, tc := range tests {
		got := maskConnString(tc.input)
		if got != tc.expected {
			t.Errorf("maskConnString(%q) = %q; want %q", tc.input, got, tc.expected)
		}
	}
}
