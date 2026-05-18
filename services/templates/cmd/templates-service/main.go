package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
)

type Config struct {
	DatabaseURL                  string
	SecretKey                    string
	SessionCookieName            string
	Port                         string
}

type server struct {
	db     *pgxpool.Pool
	config Config
}

type User struct {
	ID        uuid.UUID
	Email     string
	Role      string
	IsActive  bool
	CompanyID *uuid.UUID // Evaluated during authentication
}

type InterviewTemplate struct {
	ID          uuid.UUID `json:"template_id"`
	CompanyID   uuid.UUID `json:"company_id"`
	Name        string    `json:"name"`
	TargetRole  string    `json:"target_role"`
	Questions   []string  `json:"questions"`
	Description *string   `json:"description"`
	IsPublic    bool      `json:"is_public"`
	CreatedAt   time.Time `json:"created_at"`
}

type TemplateCreateRequest struct {
	Name        string   `json:"name"`
	TargetRole  string   `json:"target_role"`
	Questions   []string `json:"questions"`
	Description *string  `json:"description"`
	IsPublic    bool     `json:"is_public"`
}

func main() {
	config := loadConfig()
	log.Printf("Connecting to Postgres database at %s...", maskConnString(config.DatabaseURL))

	var pool *pgxpool.Pool
	var err error
	for i := 0; i < 10; i++ {
		pool, err = pgxpool.New(context.Background(), config.DatabaseURL)
		if err == nil {
			err = pool.Ping(context.Background())
			if err == nil {
				break
			}
		}
		log.Printf("Postgres not ready (attempt %d/10): %v. Retrying in 2 seconds...", i+1, err)
		time.Sleep(2 * time.Second)
	}

	if err != nil {
		log.Fatalf("Failed to connect to database: %v", err)
	}
	defer pool.Close()
	log.Println("Database connection established successfully.")

	srv := &server{
		db:     pool,
		config: config,
	}

	mux := http.NewServeMux()
	mux.HandleFunc("GET /health", srv.handleHealth)
	mux.HandleFunc("GET /api/v1/company/templates", srv.handleListTemplates)
	mux.HandleFunc("POST /api/v1/company/templates", srv.handleCreateTemplate)
	mux.HandleFunc("DELETE /api/v1/company/templates/{template_id}", srv.handleDeleteTemplate)
	mux.HandleFunc("GET /api/v1/interviews/templates/public", srv.handleListPublicTemplates)

	log.Printf("Templates service listening on port %s", config.Port)
	if err := http.ListenAndServe(config.Port, mux); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func (srv *server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("OK"))
}

func (srv *server) handleListTemplates(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	if user.CompanyID == nil {
		writeError(w, http.StatusForbidden, "Company access required")
		return
	}

	query := `
		SELECT id, company_id, name, target_role, questions, description, is_public, created_at 
		FROM interview_templates 
		WHERE company_id = $1 
		ORDER BY created_at DESC
	`
	rows, err := srv.db.Query(r.Context(), query, *user.CompanyID)
	if err != nil {
		log.Printf("[TEMPLATES] Failed to list templates: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	defer rows.Close()

	templates := []InterviewTemplate{}
	for rows.Next() {
		var t InterviewTemplate
		var qBytes []byte
		err := rows.Scan(&t.ID, &t.CompanyID, &t.Name, &t.TargetRole, &qBytes, &t.Description, &t.IsPublic, &t.CreatedAt)
		if err != nil {
			log.Printf("[TEMPLATES] Failed to scan template row: %v", err)
			writeError(w, http.StatusInternalServerError, "Internal server error")
			return
		}
		if err := json.Unmarshal(qBytes, &t.Questions); err != nil {
			t.Questions = []string{}
		}
		templates = append(templates, t)
	}

	writeJSON(w, http.StatusOK, templates)
}

func (srv *server) handleCreateTemplate(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	if user.Role != "company_admin" || user.CompanyID == nil {
		writeError(w, http.StatusForbidden, "Only the company admin can create templates")
		return
	}

	var req TemplateCreateRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request payload")
		return
	}

	req.Name = strings.TrimSpace(req.Name)
	req.TargetRole = strings.TrimSpace(req.TargetRole)
	if req.Name == "" || len(req.Questions) == 0 {
		writeError(w, http.StatusUnprocessableEntity, "Name and questions are required")
		return
	}

	// 1. Check for duplicate name in this company
	var exists bool
	dupQuery := `SELECT EXISTS(SELECT 1 FROM interview_templates WHERE company_id = $1 AND name = $2)`
	err = srv.db.QueryRow(r.Context(), dupQuery, *user.CompanyID, req.Name).Scan(&exists)
	if err != nil {
		log.Printf("[TEMPLATES] Failed to check duplicate template name: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "Template with this name already exists")
		return
	}

	// 2. Insert new template
	tmplID := uuid.New()
	now := time.Now().UTC()
	qBytes, _ := json.Marshal(req.Questions)

	insertQuery := `
		INSERT INTO interview_templates (id, company_id, name, target_role, questions, description, is_public, created_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
	`
	_, err = srv.db.Exec(r.Context(), insertQuery, tmplID, *user.CompanyID, req.Name, req.TargetRole, qBytes, req.Description, req.IsPublic, now)
	if err != nil {
		log.Printf("[TEMPLATES] Failed to create template: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	writeJSON(w, http.StatusCreated, InterviewTemplate{
		ID:          tmplID,
		CompanyID:   *user.CompanyID,
		Name:        req.Name,
		TargetRole:  req.TargetRole,
		Questions:   req.Questions,
		Description: req.Description,
		IsPublic:    req.IsPublic,
		CreatedAt:   now,
	})
}

func (srv *server) handleDeleteTemplate(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	if user.Role != "company_admin" || user.CompanyID == nil {
		writeError(w, http.StatusForbidden, "Only the company admin can delete templates")
		return
	}

	templateIDStr := r.PathValue("template_id")
	templateID, err := uuid.Parse(templateIDStr)
	if err != nil {
		writeError(w, http.StatusBadRequest, "Invalid template ID format")
		return
	}

	// 1. Get the template to verify ownership
	var companyID uuid.UUID
	err = srv.db.QueryRow(r.Context(), "SELECT company_id FROM interview_templates WHERE id = $1", templateID).Scan(&companyID)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeError(w, http.StatusNotFound, "Template not found")
			return
		}
		log.Printf("[TEMPLATES] Failed to get template for delete: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	if companyID != *user.CompanyID {
		writeError(w, http.StatusForbidden, "Not your template")
		return
	}

	// 2. Perform the delete
	_, err = srv.db.Exec(r.Context(), "DELETE FROM interview_templates WHERE id = $1", templateID)
	if err != nil {
		log.Printf("[TEMPLATES] Failed to delete template: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (srv *server) handleListPublicTemplates(w http.ResponseWriter, r *http.Request) {
	query := `
		SELECT id, company_id, name, target_role, questions, description, is_public, created_at 
		FROM interview_templates 
		WHERE is_public = true 
		ORDER BY created_at DESC
	`
	rows, err := srv.db.Query(r.Context(), query)
	if err != nil {
		log.Printf("[TEMPLATES] Failed to list public templates: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	defer rows.Close()

	templates := []InterviewTemplate{}
	for rows.Next() {
		var t InterviewTemplate
		var qBytes []byte
		err := rows.Scan(&t.ID, &t.CompanyID, &t.Name, &t.TargetRole, &qBytes, &t.Description, &t.IsPublic, &t.CreatedAt)
		if err != nil {
			log.Printf("[TEMPLATES] Failed to scan public template row: %v", err)
			writeError(w, http.StatusInternalServerError, "Internal server error")
			return
		}
		if err := json.Unmarshal(qBytes, &t.Questions); err != nil {
			t.Questions = []string{}
		}
		templates = append(templates, t)
	}

	writeJSON(w, http.StatusOK, templates)
}

// Authentication Helpers

func (srv *server) authenticateUser(r *http.Request) (User, error) {
	var tokenStr string

	// 1. Try Authorization Bearer header first
	authHeader := r.Header.Get("Authorization")
	if strings.HasPrefix(authHeader, "Bearer ") {
		tStr := strings.TrimPrefix(authHeader, "Bearer ")
		token, err := jwt.Parse(tStr, func(token *jwt.Token) (interface{}, error) {
			if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
			}
			return []byte(srv.config.SecretKey), nil
		})
		if err == nil && token.Valid {
			tokenStr = tStr
		}
	}

	// 2. Try Cookie if Bearer was missing or invalid
	if tokenStr == "" {
		cookie, err := r.Cookie(srv.config.SessionCookieName)
		if err == nil {
			tokenStr = cookie.Value
		}
	}

	if tokenStr == "" {
		return User{}, fmt.Errorf("no credentials found")
	}

	token, err := jwt.Parse(tokenStr, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, fmt.Errorf("unexpected signing method: %v", token.Header["alg"])
		}
		return []byte(srv.config.SecretKey), nil
	})

	if err != nil || !token.Valid {
		return User{}, fmt.Errorf("invalid token: %v", err)
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		return User{}, fmt.Errorf("invalid claims")
	}

	sub, ok := claims["sub"].(string)
	if !ok {
		return User{}, fmt.Errorf("missing sub claim")
	}

	userID, err := uuid.Parse(sub)
	if err != nil {
		return User{}, fmt.Errorf("invalid sub uuid: %v", err)
	}

	var u User
	err = srv.db.QueryRow(r.Context(), "SELECT id, email, role, is_active FROM users WHERE id = $1", userID).Scan(
		&u.ID, &u.Email, &u.Role, &u.IsActive,
	)
	if err != nil {
		return User{}, err
	}

	if !u.IsActive {
		return User{}, fmt.Errorf("user is inactive")
	}

	// Evaluate User Company ID
	if u.Role == "company_admin" {
		var cID uuid.UUID
		err = srv.db.QueryRow(r.Context(), "SELECT id FROM companies WHERE owner_user_id = $1", u.ID).Scan(&cID)
		if err == nil {
			u.CompanyID = &cID
		}
	} else if u.Role == "company_member" {
		var cID uuid.UUID
		err = srv.db.QueryRow(r.Context(), "SELECT company_id FROM company_members WHERE user_id = $1", u.ID).Scan(&cID)
		if err == nil {
			u.CompanyID = &cID
		}
	}

	return u, nil
}

// Config & String Helpers

func loadConfig() Config {
	return Config{
		DatabaseURL:       normalizeDatabaseURL(os.Getenv("DATABASE_URL")),
		SecretKey:         envOrDefault("SECRET_KEY", "dev-secret-key-change-me"),
		SessionCookieName: envOrDefault("SESSION_COOKIE_NAME", "airecruit_session"),
		Port:              envOrDefault("PORT", ":8080"),
	}
}

func normalizeDatabaseURL(value string) string {
	normalized := strings.TrimSpace(value)
	normalized = strings.Replace(normalized, "postgresql+asyncpg://", "postgres://", 1)
	normalized = strings.Replace(normalized, "postgres+asyncpg://", "postgres://", 1)
	return normalized
}

func maskConnString(url string) string {
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

func envOrDefault(key string, fallback string) string {
	val := strings.TrimSpace(os.Getenv(key))
	if val == "" {
		return fallback
	}
	return val
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
