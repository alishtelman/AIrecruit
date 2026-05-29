package db

import (
	"context"
	"fmt"
	"log"
	"os"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/pgxpool"
)

// Connect establishes a robust connection pool to PostgreSQL.
func Connect(ctx context.Context) (*pgxpool.Pool, error) {
	dbURL := GetDatabaseURL()
	log.Printf("Connecting to Postgres database at %s...", MaskConnString(dbURL))

	var pool *pgxpool.Pool
	var err error
	for i := 0; i < 10; i++ {
		pool, err = pgxpool.New(ctx, dbURL)
		if err == nil {
			err = pool.Ping(ctx)
			if err == nil {
				break
			}
		}
		log.Printf("Postgres not ready (attempt %d/10): %v. Retrying in 2 seconds...", i+1, err)
		select {
		case <-ctx.Done():
			return nil, ctx.Err()
		case <-time.After(2 * time.Second):
		}
	}

	if err != nil {
		return nil, fmt.Errorf("failed to connect to database after retries: %w", err)
	}

	log.Println("Database connection established successfully.")
	return pool, nil
}

// GetDatabaseURL returns normalized DATABASE_URL from environment variables.
func GetDatabaseURL() string {
	val := os.Getenv("DATABASE_URL")
	if val == "" {
		// Fallback to local dev db URL
		val = "postgres://recruiting:recruiting@postgres:5432/recruiting"
	}
	return NormalizeDatabaseURL(val)
}

// NormalizeDatabaseURL strips SQLAlchemy-specific async prefixes.
func NormalizeDatabaseURL(value string) string {
	normalized := strings.TrimSpace(value)
	normalized = strings.Replace(normalized, "postgresql+asyncpg://", "postgres://", 1)
	normalized = strings.Replace(normalized, "postgres+asyncpg://", "postgres://", 1)
	return normalized
}

// MaskConnString hides database credentials from logs.
func MaskConnString(url string) string {
	parts := strings.Split(url, "@")
	if len(parts) < 2 {
		return "[redacted]"
	}
	subparts := strings.Split(parts[0], "://")
	if len(subparts) < 2 {
		return "postgres://***:***@" + parts[1]
	}
	return subparts[0] + "://***:***@" + parts[1]
}
