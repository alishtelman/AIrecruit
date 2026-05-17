package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"log"
	"net/http"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
	"github.com/jackc/pgx/v5"
	"github.com/jackc/pgx/v5/pgxpool"
	"golang.org/x/crypto/bcrypt"
)

type Config struct {
	DatabaseURL                  string
	SecretKey                    string
	Algorithm                    string
	SessionCookieName            string
	SessionCookieSecure          bool
	SessionCookieSameSite        string
	AccessTokenExpireMinutes    int
	PlatformAdminBootstrap       bool
	PlatformAdminEmail           string
	PlatformAdminPassword        string
	Port                         string
}

func loadConfig() Config {
	return Config{
		DatabaseURL:               normalizeDatabaseURL(os.Getenv("DATABASE_URL")),
		SecretKey:                 envOrDefault("SECRET_KEY", "dev-secret-key-change-me"),
		Algorithm:                 envOrDefault("ALGORITHM", "HS256"),
		SessionCookieName:         envOrDefault("SESSION_COOKIE_NAME", "airecruit_session"),
		SessionCookieSecure:       os.Getenv("SESSION_COOKIE_SECURE") == "true",
		SessionCookieSameSite:     envOrDefault("SESSION_COOKIE_SAMESITE", "lax"),
		AccessTokenExpireMinutes:  envAsInt("ACCESS_TOKEN_EXPIRE_MINUTES", 10080),
		PlatformAdminBootstrap:    envAsBool("PLATFORM_ADMIN_BOOTSTRAP_ENABLED", true),
		PlatformAdminEmail:        envOrDefault("PLATFORM_ADMIN_EMAIL", "admin@airecruit.ai"),
		PlatformAdminPassword:     envOrDefault("PLATFORM_ADMIN_PASSWORD", "admin12345"),
		Port:                      envOrDefault("PORT", ":8080"),
	}
}

type server struct {
	db     *pgxpool.Pool
	config Config
}

type User struct {
	ID             uuid.UUID `json:"id"`
	Email          string    `json:"email"`
	HashedPassword string    `json:"-"`
	Role           string    `json:"role"`
	IsActive       bool      `json:"is_active"`
	CreatedAt      time.Time `json:"created_at"`
	UpdatedAt      time.Time `json:"updated_at"`
}

type Candidate struct {
	ID                uuid.UUID `json:"id"`
	UserID            uuid.UUID `json:"user_id"`
	FullName          string    `json:"full_name"`
	SalaryMin         *int      `json:"salary_min"`
	SalaryMax         *int      `json:"salary_max"`
	SalaryCurrency    string    `json:"salary_currency"`
	ProfileVisibility string    `json:"profile_visibility"`
	PublicShareToken  *string   `json:"public_share_token"`
	CreatedAt         time.Time `json:"created_at"`
	UpdatedAt         time.Time `json:"updated_at"`
}

type Company struct {
	ID          uuid.UUID `json:"id"`
	OwnerUserID uuid.UUID `json:"owner_user_id"`
	Name        string    `json:"name"`
	IsActive    bool      `json:"is_active"`
}

type UserResponse struct {
	ID                uuid.UUID  `json:"id"`
	Email             string     `json:"email"`
	Role              string     `json:"role"`
	CompanyMemberRole *string    `json:"company_member_role"`
	CompanyID         *uuid.UUID `json:"company_id"`
	IsActive          bool       `json:"is_active"`
	CreatedAt         time.Time  `json:"created_at"`
}

type CandidateResponse struct {
	ID       uuid.UUID `json:"id"`
	UserID   uuid.UUID `json:"user_id"`
	FullName string    `json:"full_name"`
}

type CandidateWithUserResponse struct {
	User      UserResponse      `json:"user"`
	Candidate CandidateResponse `json:"candidate"`
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
	mux.HandleFunc("/health", srv.handleHealth)
	mux.HandleFunc("/api/v1/auth/candidate/register", srv.handleCandidateRegister)
	mux.HandleFunc("/api/v1/auth/company/register", srv.handleCompanyRegister)
	mux.HandleFunc("/api/v1/auth/login", srv.handleLogin)
	mux.HandleFunc("/api/v1/auth/logout", srv.handleLogout)
	mux.HandleFunc("/api/v1/auth/me", srv.handleMe)
	mux.HandleFunc("/api/v1/auth/me/candidate", srv.handleMeCandidate)
	mux.HandleFunc("/api/v1/auth/change-password", srv.handleChangePassword)

	log.Printf("Auth service listening on port %s", config.Port)
	if err := http.ListenAndServe(config.Port, mux); err != nil {
		log.Fatalf("Server failed: %v", err)
	}
}

func (srv *server) handleHealth(w http.ResponseWriter, r *http.Request) {
	w.WriteHeader(http.StatusOK)
	w.Write([]byte("OK"))
}

type CandidateRegisterRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
	FullName string `json:"full_name"`
}

func (srv *server) handleCandidateRegister(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	var req CandidateRegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request payload")
		return
	}

	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	req.FullName = strings.TrimSpace(req.FullName)
	req.Password = strings.TrimSpace(req.Password)

	if req.Email == "" || req.Password == "" || req.FullName == "" {
		writeError(w, http.StatusUnprocessableEntity, "Email, password, and full name are required")
		return
	}

	// 1. Verify if candidate registration is enabled in platform settings
	regEnabled, err := srv.isCandidateRegistrationEnabled(r.Context())
	if err != nil {
		log.Printf("[AUTH] Failed to check platform settings: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if !regEnabled {
		writeError(w, http.StatusForbidden, "Candidate registration is temporarily disabled.")
		return
	}

	// 2. Check if email already exists
	exists, err := srv.checkUserExists(r.Context(), req.Email)
	if err != nil {
		log.Printf("[AUTH] Failed to check user existence: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "Email already registered")
		return
	}

	// 3. Hash password
	hashed, err := hashPassword(req.Password)
	if err != nil {
		log.Printf("[AUTH] Failed to hash password: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	// 4. Start Transaction to insert user and candidate
	tx, err := srv.db.Begin(r.Context())
	if err != nil {
		log.Printf("[AUTH] Failed to start tx: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	defer tx.Rollback(r.Context())

	userID := uuid.New()
	now := time.Now().UTC()

	// Insert User
	userQuery := `
		INSERT INTO users (id, email, hashed_password, role, is_active, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`
	_, err = tx.Exec(r.Context(), userQuery, userID, req.Email, hashed, "candidate", true, now, now)
	if err != nil {
		log.Printf("[AUTH] Failed to insert user: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	candidateID := uuid.New()
	// Insert Candidate
	candidateQuery := `
		INSERT INTO candidates (id, user_id, full_name, salary_min, salary_max, salary_currency, profile_visibility, public_share_token, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
	`
	_, err = tx.Exec(r.Context(), candidateQuery, candidateID, userID, req.FullName, nil, nil, "USD", "marketplace", nil, now, now)
	if err != nil {
		log.Printf("[AUTH] Failed to insert candidate: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	if err := tx.Commit(r.Context()); err != nil {
		log.Printf("[AUTH] Failed to commit tx: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	writeJSON(w, http.StatusCreated, CandidateWithUserResponse{
		User: UserResponse{
			ID:                userID,
			Email:             req.Email,
			Role:              "candidate",
			CompanyMemberRole: nil,
			CompanyID:         nil,
			IsActive:          true,
			CreatedAt:         now,
		},
		Candidate: CandidateResponse{
			ID:       candidateID,
			UserID:   userID,
			FullName: req.FullName,
		},
	})
}

type CompanyRegisterRequest struct {
	Email       string `json:"email"`
	Password    string `json:"password"`
	CompanyName string `json:"company_name"`
}

type CompanyRegisterResponse struct {
	UserID      uuid.UUID `json:"user_id"`
	Email       string    `json:"email"`
	CompanyID   uuid.UUID `json:"company_id"`
	CompanyName string    `json:"company_name"`
}

func (srv *server) handleCompanyRegister(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	var req CompanyRegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request payload")
		return
	}

	req.Email = strings.ToLower(strings.TrimSpace(req.Email))
	req.CompanyName = strings.TrimSpace(req.CompanyName)
	req.Password = strings.TrimSpace(req.Password)

	if req.Email == "" || req.Password == "" || req.CompanyName == "" {
		writeError(w, http.StatusUnprocessableEntity, "Email, password, and company name are required")
		return
	}

	// 1. Verify if company registration is enabled in platform settings
	regEnabled, err := srv.isCompanyRegistrationEnabled(r.Context())
	if err != nil {
		log.Printf("[AUTH] Failed to check platform settings: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if !regEnabled {
		writeError(w, http.StatusForbidden, "Company registration is temporarily disabled.")
		return
	}

	// 2. Check if email already exists
	exists, err := srv.checkUserExists(r.Context(), req.Email)
	if err != nil {
		log.Printf("[AUTH] Failed to check user existence: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	if exists {
		writeError(w, http.StatusConflict, "Email already registered")
		return
	}

	// 3. Hash password
	hashed, err := hashPassword(req.Password)
	if err != nil {
		log.Printf("[AUTH] Failed to hash password: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	// 4. Start Transaction to insert user and company
	tx, err := srv.db.Begin(r.Context())
	if err != nil {
		log.Printf("[AUTH] Failed to start tx: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}
	defer tx.Rollback(r.Context())

	userID := uuid.New()
	now := time.Now().UTC()

	// Insert User
	userQuery := `
		INSERT INTO users (id, email, hashed_password, role, is_active, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`
	_, err = tx.Exec(r.Context(), userQuery, userID, req.Email, hashed, "company_admin", true, now, now)
	if err != nil {
		log.Printf("[AUTH] Failed to insert user: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	companyID := uuid.New()
	// Insert Company
	companyQuery := `
		INSERT INTO companies (id, owner_user_id, name, is_active, ai_settings, created_at, updated_at)
		VALUES ($1, $2, $3, $4, $5, $6, $7)
	`
	_, err = tx.Exec(r.Context(), companyQuery, companyID, userID, req.CompanyName, true, nil, now, now)
	if err != nil {
		log.Printf("[AUTH] Failed to insert company: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	if err := tx.Commit(r.Context()); err != nil {
		log.Printf("[AUTH] Failed to commit tx: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	writeJSON(w, http.StatusCreated, CompanyRegisterResponse{
		UserID:      userID,
		Email:       req.Email,
		CompanyID:   companyID,
		CompanyName: req.CompanyName,
	})
}

type LoginRequest struct {
	Email    string `json:"email"`
	Password string `json:"password"`
}

type TokenResponse struct {
	AccessToken string `json:"access_token"`
	TokenType   string `json:"token_type"`
}

func (srv *server) handleLogin(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	var req LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request payload")
		return
	}

	req.Email = strings.ToLower(strings.TrimSpace(req.Email))

	// 1. Bootstrap Platform Admin if bootstrap configs match and user is trying to login as admin
	if srv.config.PlatformAdminBootstrap && req.Email == strings.ToLower(srv.config.PlatformAdminEmail) {
		err := srv.ensurePlatformAdmin(r.Context())
		if err != nil {
			log.Printf("[AUTH] Platform admin bootstrap failed: %v", err)
		}
	}

	// 2. Retrieve user
	user, err := srv.getUserByEmail(r.Context(), req.Email)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeError(w, http.StatusUnauthorized, "Invalid email or password")
			return
		}
		log.Printf("[AUTH] Failed to load user: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	// 3. Verify password
	if !verifyPassword(req.Password, user.HashedPassword) {
		writeError(w, http.StatusUnauthorized, "Invalid email or password")
		return
	}

	// 4. Verify is active
	if !user.IsActive {
		writeError(w, http.StatusUnauthorized, "Invalid email or password")
		return
	}

	// 5. Generate JWT token
	tokenStr, err := srv.createAccessToken(user.ID.String(), user.Role)
	if err != nil {
		log.Printf("[AUTH] Failed to generate access token: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	// 6. Set auth session cookie
	sameSite := http.SameSiteLaxMode
	if strings.ToLower(srv.config.SessionCookieSameSite) == "none" {
		sameSite = http.SameSiteNoneMode
	} else if strings.ToLower(srv.config.SessionCookieSameSite) == "strict" {
		sameSite = http.SameSiteStrictMode
	}

	http.SetCookie(w, &http.Cookie{
		Name:     srv.config.SessionCookieName,
		Value:    tokenStr,
		Path:     "/",
		MaxAge:   srv.config.AccessTokenExpireMinutes * 60,
		Secure:   srv.config.SessionCookieSecure,
		HttpOnly: true,
		SameSite: sameSite,
	})

	writeJSON(w, http.StatusOK, TokenResponse{
		AccessToken: tokenStr,
		TokenType:   "bearer",
	})
}

func (srv *server) handleLogout(w http.ResponseWriter, r *http.Request) {
	// Clear cookie
	sameSite := http.SameSiteLaxMode
	if strings.ToLower(srv.config.SessionCookieSameSite) == "none" {
		sameSite = http.SameSiteNoneMode
	} else if strings.ToLower(srv.config.SessionCookieSameSite) == "strict" {
		sameSite = http.SameSiteStrictMode
	}

	http.SetCookie(w, &http.Cookie{
		Name:     srv.config.SessionCookieName,
		Value:    "",
		Path:     "/",
		MaxAge:   -1,
		Secure:   srv.config.SessionCookieSecure,
		HttpOnly: true,
		SameSite: sameSite,
	})

	w.WriteHeader(http.StatusNoContent)
}

func (srv *server) handleMe(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	var companyMemberRole *string
	var companyID *uuid.UUID

	if user.Role == "company_admin" {
		roleAdmin := "admin"
		companyMemberRole = &roleAdmin

		// Load Company
		var cID uuid.UUID
		err = srv.db.QueryRow(r.Context(), "SELECT id FROM companies WHERE owner_user_id = $1", user.ID).Scan(&cID)
		if err == nil {
			companyID = &cID
		}
	} else if user.Role == "company_member" {
		var cID uuid.UUID
		var mRole string
		err = srv.db.QueryRow(r.Context(), "SELECT company_id, role FROM company_members WHERE user_id = $1", user.ID).Scan(&cID, &mRole)
		if err == nil {
			companyID = &cID
			if mRole == "member" {
				recruiterRole := "recruiter"
				companyMemberRole = &recruiterRole
			} else {
				companyMemberRole = &mRole
			}
		}
	}

	writeJSON(w, http.StatusOK, UserResponse{
		ID:                user.ID,
		Email:             user.Email,
		Role:              user.Role,
		CompanyMemberRole: companyMemberRole,
		CompanyID:         companyID,
		IsActive:          user.IsActive,
		CreatedAt:         user.CreatedAt,
	})
}

func (srv *server) handleMeCandidate(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	if user.Role != "candidate" {
		writeError(w, http.StatusForbidden, "Candidate access required")
		return
	}

	var candID uuid.UUID
	var fullName string
	err = srv.db.QueryRow(r.Context(), "SELECT id, full_name FROM candidates WHERE user_id = $1", user.ID).Scan(&candID, &fullName)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			writeError(w, http.StatusNotFound, "Candidate profile not found")
			return
		}
		log.Printf("[AUTH] Failed to query candidate: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	writeJSON(w, http.StatusOK, CandidateWithUserResponse{
		User: UserResponse{
			ID:                user.ID,
			Email:             user.Email,
			Role:              user.Role,
			CompanyMemberRole: nil,
			CompanyID:         nil,
			IsActive:          user.IsActive,
			CreatedAt:         user.CreatedAt,
		},
		Candidate: CandidateResponse{
			ID:       candID,
			UserID:   user.ID,
			FullName: fullName,
		},
	})
}

type ChangePasswordRequest struct {
	CurrentPassword string `json:"current_password"`
	NewPassword     string `json:"new_password"`
}

type csrfError struct {
	detail string
}

func (e csrfError) Error() string {
	return e.detail
}

func (srv *server) handleChangePassword(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		writeError(w, http.StatusMethodNotAllowed, "Method not allowed")
		return
	}

	user, err := srv.authenticateUser(r)
	if err != nil {
		var cErr csrfError
		if errors.As(err, &cErr) {
			writeError(w, http.StatusForbidden, err.Error())
			return
		}
		writeError(w, http.StatusUnauthorized, "Could not validate credentials")
		return
	}

	var req ChangePasswordRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request payload")
		return
	}

	if !verifyPassword(req.CurrentPassword, user.HashedPassword) {
		writeError(w, http.StatusBadRequest, "Current password is incorrect")
		return
	}

	if len(req.NewPassword) < 8 {
		writeError(w, http.StatusBadRequest, "New password must be at least 8 characters")
		return
	}

	hashed, err := hashPassword(req.NewPassword)
	if err != nil {
		log.Printf("[AUTH] Failed to hash password: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	_, err = srv.db.Exec(r.Context(), "UPDATE users SET hashed_password = $1, updated_at = $2 WHERE id = $3", hashed, time.Now().UTC(), user.ID)
	if err != nil {
		log.Printf("[AUTH] Failed to update password: %v", err)
		writeError(w, http.StatusInternalServerError, "Internal server error")
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

// Helper DB & Crypt functions

func (srv *server) isCandidateRegistrationEnabled(ctx context.Context) (bool, error) {
	var enabled bool
	err := srv.db.QueryRow(ctx, "SELECT candidate_registration_enabled FROM platform_settings WHERE id = 1").Scan(&enabled)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return true, nil // default true if table not initialized
		}
		return false, err
	}
	return enabled, nil
}

func (srv *server) isCompanyRegistrationEnabled(ctx context.Context) (bool, error) {
	var enabled bool
	err := srv.db.QueryRow(ctx, "SELECT company_registration_enabled FROM platform_settings WHERE id = 1").Scan(&enabled)
	if err != nil {
		if errors.Is(err, pgx.ErrNoRows) {
			return true, nil // default true if table not initialized
		}
		return false, err
	}
	return enabled, nil
}

func (srv *server) checkUserExists(ctx context.Context, email string) (bool, error) {
	var exists bool
	err := srv.db.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM users WHERE email = $1)", email).Scan(&exists)
	return exists, err
}

func (srv *server) getUserByEmail(ctx context.Context, email string) (User, error) {
	var u User
	err := srv.db.QueryRow(ctx, "SELECT id, email, hashed_password, role, is_active, created_at, updated_at FROM users WHERE email = $1", email).Scan(
		&u.ID, &u.Email, &u.HashedPassword, &u.Role, &u.IsActive, &u.CreatedAt, &u.UpdatedAt,
	)
	return u, err
}

func (srv *server) ensurePlatformAdmin(ctx context.Context) error {
	var exists bool
	err := srv.db.QueryRow(ctx, "SELECT EXISTS(SELECT 1 FROM users WHERE email = $1)", strings.ToLower(srv.config.PlatformAdminEmail)).Scan(&exists)
	if err != nil {
		return err
	}
	if exists {
		return nil
	}

	hashed, err := hashPassword(srv.config.PlatformAdminPassword)
	if err != nil {
		return err
	}

	userID := uuid.New()
	now := time.Now().UTC()
	_, err = srv.db.Exec(ctx,
		"INSERT INTO users (id, email, hashed_password, role, is_active, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
		userID, strings.ToLower(srv.config.PlatformAdminEmail), hashed, "platform_admin", true, now, now,
	)
	if err == nil {
		log.Printf("[AUTH] Platform admin %s bootstrapped successfully.", srv.config.PlatformAdminEmail)
	}
	return err
}

func (srv *server) createAccessToken(subject string, role string) (string, error) {
	expTime := time.Now().Add(time.Duration(srv.config.AccessTokenExpireMinutes) * time.Minute)
	token := jwt.NewWithClaims(jwt.SigningMethodHS256, jwt.MapClaims{
		"sub":  subject,
		"role": role,
		"exp":  expTime.Unix(),
	})
	return token.SignedString([]byte(srv.config.SecretKey))
}

func (srv *server) enforceCSRF(r *http.Request) error {
	method := strings.ToUpper(r.Method)
	if method != "POST" && method != "PUT" && method != "PATCH" && method != "DELETE" {
		return nil
	}

	origin := r.Header.Get("Origin")
	if origin == "" {
		origin = r.Header.Get("Referer")
	}
	if origin == "" {
		return csrfError{detail: "CSRF validation failed"}
	}

	trustedStr := os.Getenv("CSRF_TRUSTED_ORIGINS")
	if trustedStr == "" {
		trustedStr = os.Getenv("CORS_ORIGINS")
	}
	if trustedStr == "" {
		trustedStr = "http://localhost:3000,http://127.0.0.1:3000"
	}

	var trustedOrigins []string
	for _, raw := range strings.Split(trustedStr, ",") {
		trimmed := strings.TrimSpace(raw)
		if trimmed != "" {
			trustedOrigins = append(trustedOrigins, trimmed)
		}
	}

	normalizedRequestOrigin := normalizeOrigin(origin)

	for _, o := range trustedOrigins {
		if o == "*" || strings.Contains(o, "*") {
			return nil
		}
		if normalizeOrigin(o) == normalizedRequestOrigin {
			return nil
		}
	}

	return csrfError{detail: "CSRF validation failed"}
}

func normalizeOrigin(raw string) string {
	raw = strings.TrimSpace(strings.ToLower(raw))
	if !strings.HasPrefix(raw, "http://") && !strings.HasPrefix(raw, "https://") {
		return raw
	}
	u, err := url.Parse(raw)
	if err != nil {
		return raw
	}
	return fmt.Sprintf("%s://%s", u.Scheme, u.Host)
}

func (srv *server) authenticateUser(r *http.Request) (User, error) {
	var tokenStr string
	var usedCookie bool

	// 1. Try Authorization Bearer header first (explicit, high precedence)
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
			usedCookie = false
		}
	}

	// 2. Try Cookie if Bearer was missing or invalid
	if tokenStr == "" {
		cookie, err := r.Cookie(srv.config.SessionCookieName)
		if err == nil {
			tokenStr = cookie.Value
			usedCookie = true
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
	err = srv.db.QueryRow(r.Context(), "SELECT id, email, hashed_password, role, is_active, created_at, updated_at FROM users WHERE id = $1", userID).Scan(
		&u.ID, &u.Email, &u.HashedPassword, &u.Role, &u.IsActive, &u.CreatedAt, &u.UpdatedAt,
	)
	if err != nil {
		return User{}, err
	}

	if !u.IsActive {
		return User{}, fmt.Errorf("user is inactive")
	}

	// Enforce CSRF if using Cookie for unsafe methods
	if usedCookie {
		if err := srv.enforceCSRF(r); err != nil {
			return User{}, err
		}
	}

	return u, nil
}

// String Hashing and Helper Utilities

func hashPassword(password string) (string, error) {
	bytes, err := bcrypt.GenerateFromPassword([]byte(password), bcrypt.DefaultCost)
	return string(bytes), err
}

func verifyPassword(password, hash string) bool {
	err := bcrypt.CompareHashAndPassword([]byte(hash), []byte(password))
	return err == nil
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

func envAsInt(key string, fallback int) int {
	valStr := strings.TrimSpace(os.Getenv(key))
	if valStr == "" {
		return fallback
	}
	val, err := strconv.Atoi(valStr)
	if err != nil {
		return fallback
	}
	return val
}

func envAsBool(key string, fallback bool) bool {
	valStr := strings.TrimSpace(os.Getenv(key))
	if valStr == "" {
		return fallback
	}
	return valStr == "true"
}

func writeError(w http.ResponseWriter, status int, detail string) {
	writeJSON(w, status, map[string]string{"detail": detail})
}

func writeJSON(w http.ResponseWriter, status int, payload any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(payload)
}
