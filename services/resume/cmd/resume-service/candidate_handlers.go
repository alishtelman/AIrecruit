package main

import (
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"mime/multipart"
	"net/http"
	"os"
	"path/filepath"
	"strings"
	"time"

	"github.com/golang-jwt/jwt/v5"
	"github.com/google/uuid"
)

type User struct {
	ID        string
	Role      string
	IsActive  bool
	CompanyID *string
}

type CandidateStatsResponse struct {
	HasResume       bool    `json:"has_resume"`
	InterviewCount  int     `json:"interview_count"`
	CompletedCount  int     `json:"completed_count"`
	LatestReportID  *string `json:"latest_report_id"`
}

type ActiveResumeResponse struct {
	ResumeID   string    `json:"resume_id"`
	FileName   string    `json:"file_name"`
	FileSize   int64     `json:"file_size"`
	UploadedAt time.Time `json:"uploaded_at"`
}

type ResumeTextResponse struct {
	ResumeID string `json:"resume_id"`
	FileName string `json:"file_name"`
	RawText  string `json:"raw_text"`
}

type ResumeUploadResponse struct {
	ResumeID   string `json:"resume_id"`
	FileName   string `json:"file_name"`
	TextLength int    `json:"text_length"`
	IsActive   bool   `json:"is_active"`
}

func (srv *server) authenticateUser(r *http.Request) (User, error) {
	var tokenStr string

	// 1. Try Authorization Bearer header first
	authHeader := r.Header.Get("Authorization")
	if strings.HasPrefix(authHeader, "Bearer ") {
		tStr := strings.TrimPrefix(authHeader, "Bearer ")
		token, err := jwt.Parse(tStr, func(token *jwt.Token) (interface{}, error) {
			if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
				return nil, errors.New("unexpected signing method")
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
		fmt.Println("Auth failed: no credentials found")
		return User{}, errors.New("no credentials found")
	}

	token, err := jwt.Parse(tokenStr, func(token *jwt.Token) (interface{}, error) {
		if _, ok := token.Method.(*jwt.SigningMethodHMAC); !ok {
			return nil, errors.New("unexpected signing method")
		}
		return []byte(srv.config.SecretKey), nil
	})

	if err != nil || !token.Valid {
		fmt.Println("Auth failed: invalid token:", err)
		return User{}, errors.New("invalid token")
	}

	claims, ok := token.Claims.(jwt.MapClaims)
	if !ok {
		fmt.Println("Auth failed: invalid token claims")
		return User{}, errors.New("invalid token claims")
	}

	sub, ok := claims["sub"].(string)
	if !ok {
		fmt.Println("Auth failed: invalid subject")
		return User{}, errors.New("invalid token subject")
	}

	var user User
	err = srv.db.QueryRow(r.Context(), "SELECT id, role, is_active FROM users WHERE id = $1", sub).Scan(
		&user.ID, &user.Role, &user.IsActive,
	)
	if err != nil {
		fmt.Println("Auth failed: user not found:", err)
		return User{}, errors.New("user not found")
	}
	if !user.IsActive {
		fmt.Println("Auth failed: user inactive")
		return User{}, errors.New("user is inactive")
	}

	return user, nil
}

func (srv *server) getCandidateContext(ctx context.Context, u User) (string, error) {
	if u.Role != "candidate" {
		return "", errors.New("user is not a candidate")
	}
	var candidateID string
	err := srv.db.QueryRow(ctx, "SELECT id FROM candidates WHERE user_id = $1", u.ID).Scan(&candidateID)
	if err != nil {
		return "", err
	}
	return candidateID, nil
}

func (srv *server) handleGetStats(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var stats CandidateStatsResponse
	
	// Has resume
	var resumeCount int
	err = srv.db.QueryRow(r.Context(), "SELECT COUNT(*) FROM resumes WHERE candidate_id = $1 AND is_active = true", candidateID).Scan(&resumeCount)
	if err == nil && resumeCount > 0 {
		stats.HasResume = true
	}

	// Interview count
	_ = srv.db.QueryRow(r.Context(), "SELECT COUNT(*) FROM interviews WHERE candidate_id = $1", candidateID).Scan(&stats.InterviewCount)

	// Completed count
	_ = srv.db.QueryRow(r.Context(), "SELECT COUNT(*) FROM interviews WHERE candidate_id = $1 AND status = 'report_generated'", candidateID).Scan(&stats.CompletedCount)

	// Latest report ID
	var reportID string
	err = srv.db.QueryRow(r.Context(), "SELECT id FROM assessment_reports WHERE candidate_id = $1 ORDER BY created_at DESC LIMIT 1", candidateID).Scan(&reportID)
	if err == nil {
		stats.LatestReportID = &reportID
	}

	writeJSON(w, http.StatusOK, stats)
}

func (srv *server) handleGetResume(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var resp ActiveResumeResponse
	err = srv.db.QueryRow(r.Context(), "SELECT id, file_name, file_size, created_at FROM resumes WHERE candidate_id = $1 AND is_active = true ORDER BY created_at DESC LIMIT 1", candidateID).Scan(
		&resp.ResumeID, &resp.FileName, &resp.FileSize, &resp.UploadedAt,
	)
	if err != nil {
		// Return null (Python returned None -> 200 OK with "null")
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte("null"))
		return
	}

	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleGetResumeText(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	var resp ResumeTextResponse
	var rawText *string
	err = srv.db.QueryRow(r.Context(), "SELECT id, file_name, raw_text FROM resumes WHERE candidate_id = $1 AND is_active = true ORDER BY created_at DESC LIMIT 1", candidateID).Scan(
		&resp.ResumeID, &resp.FileName, &rawText,
	)
	if err != nil {
		writeError(w, http.StatusNotFound, "No active resume found.")
		return
	}

	if rawText != nil {
		resp.RawText = *rawText
	} else {
		resp.RawText = ""
	}

	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleCandidateUpload(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	if err := r.ParseMultipartForm(srv.maxBytes); err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "file exceeds maximum allowed size")
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "file field is required")
		return
	}
	defer file.Close()

	// Process upload (extract text, save to disk)
	start := time.Now()
	result, err := srv.processUpload(file, header)
	srv.upload.record(time.Since(start), err)
	if err != nil {
		var httpErr httpError
		if errors.As(err, &httpErr) {
			writeError(w, httpErr.status, httpErr.detail)
			return
		}
		writeError(w, http.StatusUnprocessableEntity, err.Error())
		return
	}

	// Deactivate previous resumes
	_, err = srv.db.Exec(r.Context(), "UPDATE resumes SET is_active = false WHERE candidate_id = $1 AND is_active = true", candidateID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to deactivate old resumes")
		return
	}

	now := time.Now().UTC()
	newResumeID := uuid.New().String()
	
	fileName := header.Filename
	if fileName == "" {
		fileName = "resume"
	}

	// Insert new resume
	_, err = srv.db.Exec(r.Context(), `
		INSERT INTO resumes (id, candidate_id, file_name, file_path, file_size, raw_text, is_active, created_at, updated_at) 
		VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)`,
		newResumeID, candidateID, fileName, result.Path, result.FileSize, result.RawText, true, now, now,
	)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to save resume metadata")
		return
	}

	resp := ResumeUploadResponse{
		ResumeID:   newResumeID,
		FileName:   fileName,
		TextLength: len(result.RawText),
		IsActive:   true,
	}

	writeJSON(w, http.StatusOK, resp)
}

type ProctoringEvent struct {
	EventType  string         `json:"event_type"`
	Severity   string         `json:"severity"`
	OccurredAt *string        `json:"occurred_at"`
	Source     string         `json:"source"`
	Details    map[string]any `json:"details"`
}

type BehavioralSignalsRequest struct {
	ResponseTimes      []map[string]any `json:"response_times"`
	PasteCount         int              `json:"paste_count"`
	TabSwitches        int              `json:"tab_switches"`
	FaceAwayPct        *float64         `json:"face_away_pct"`
	SpeechActivityPct  *float64         `json:"speech_activity_pct"`
	SilencePct         *float64         `json:"silence_pct"`
	LongSilenceCount   int              `json:"long_silence_count"`
	SpeechSegmentCount int              `json:"speech_segment_count"`
	Events             []ProctoringEvent `json:"events"`
	PolicyMode         *string          `json:"policy_mode"`
}

func normalizeEvent(raw ProctoringEvent, index int, policyMode string) ProctoringEvent {
	eventType := strings.TrimSpace(strings.ToLower(raw.EventType))
	if eventType == "" {
		eventType = fmt.Sprintf("event_%d", index+1)
	}

	severity := strings.TrimSpace(strings.ToLower(raw.Severity))
	if severity != "info" && severity != "medium" && severity != "high" {
		severity = "info"
	}

	if policyMode == "strict_flagging" {
		strictHigh := map[string]bool{
			"multiple_faces_detected": true,
			"camera_stream_lost":      true,
		}
		strictMedium := map[string]bool{
			"paste_detected":               true,
			"tab_switch":                   true,
			"screen_share_stopped":         true,
			"screen_permission_denied":     true,
			"camera_permission_denied":     true,
			"microphone_permission_denied": true,
			"recording_upload_failed":      true,
		}
		if strictHigh[eventType] {
			severity = "high"
		} else if strictMedium[eventType] && severity == "info" {
			severity = "medium"
		}
	}

	occurredAt := raw.OccurredAt
	if occurredAt != nil {
		rawStr := strings.TrimSpace(*occurredAt)
		if rawStr != "" {
			rawStr = strings.Replace(rawStr, "Z", "+00:00", 1)
			t, err := time.Parse(time.RFC3339, rawStr)
			if err == nil {
				formatted := t.Format(time.RFC3339)
				occurredAt = &formatted
			} else {
				t2, err2 := time.Parse("2006-01-02T15:04:05", rawStr)
				if err2 == nil {
					formatted := t2.Format(time.RFC3339)
					occurredAt = &formatted
				} else {
					occurredAt = nil
				}
			}
		} else {
			occurredAt = nil
		}
	}

	source := strings.TrimSpace(strings.ToLower(raw.Source))
	if source == "" {
		source = "client"
	}

	details := raw.Details
	if details == nil {
		details = make(map[string]any)
	}

	return ProctoringEvent{
		EventType:  eventType,
		Severity:   severity,
		OccurredAt: occurredAt,
		Source:     source,
		Details:    details,
	}
}

func synthesizeEventsFromCounters(signals BehavioralSignalsRequest) []ProctoringEvent {
	var events []ProctoringEvent

	if signals.TabSwitches > 0 {
		severity := "info"
		if signals.TabSwitches >= 3 {
			severity = "medium"
		}
		events = append(events, ProctoringEvent{
			EventType: "tab_switch",
			Severity:  severity,
			Source:    "client",
			Details:   map[string]any{"count": signals.TabSwitches},
		})
	}

	if signals.PasteCount > 0 {
		severity := "info"
		if signals.PasteCount >= 2 {
			severity = "medium"
		}
		events = append(events, ProctoringEvent{
			EventType: "paste_detected",
			Severity:  severity,
			Source:    "client",
			Details:   map[string]any{"count": signals.PasteCount},
		})
	}

	if signals.FaceAwayPct != nil && *signals.FaceAwayPct >= 0.3 {
		severity := "medium"
		if *signals.FaceAwayPct >= 0.5 {
			severity = "high"
		}
		events = append(events, ProctoringEvent{
			EventType: "face_away_high",
			Severity:  severity,
			Source:    "client",
			Details:   map[string]any{"face_away_pct": mathRound(*signals.FaceAwayPct, 3)},
		})
	}

	if signals.SpeechActivityPct != nil && *signals.SpeechActivityPct < 0.08 {
		severity := "info"
		if *signals.SpeechActivityPct < 0.04 {
			severity = "medium"
		}
		details := map[string]any{
			"speech_activity_pct":  mathRound(*signals.SpeechActivityPct, 3),
			"speech_segment_count": signals.SpeechSegmentCount,
		}
		if signals.SilencePct != nil {
			details["silence_pct"] = mathRound(*signals.SilencePct, 3)
		}
		events = append(events, ProctoringEvent{
			EventType: "speech_activity_low",
			Severity:  severity,
			Source:    "client",
			Details:   details,
		})
	}

	if signals.LongSilenceCount > 0 {
		severity := "info"
		if signals.LongSilenceCount >= 2 {
			severity = "medium"
		}
		details := map[string]any{
			"count": signals.LongSilenceCount,
		}
		if signals.SilencePct != nil {
			details["silence_pct"] = mathRound(*signals.SilencePct, 3)
		}
		events = append(events, ProctoringEvent{
			EventType: "long_silence",
			Severity:  severity,
			Source:    "client",
			Details:   details,
		})
	}

	if len(signals.ResponseTimes) > 0 {
		suspiciousFastCount := 0
		for _, rt := range signals.ResponseTimes {
			if rt != nil {
				var sec float64
				if v, ok := rt["seconds"].(float64); ok {
					sec = v
				} else if v, ok := rt["seconds"].(int); ok {
					sec = float64(v)
				}
				if sec > 0 && sec <= 1.5 {
					suspiciousFastCount++
				}
			}
		}
		if suspiciousFastCount > 0 {
			events = append(events, ProctoringEvent{
				EventType: "very_fast_answers",
				Severity:  "info",
				Source:    "client",
				Details:   map[string]any{"count": suspiciousFastCount},
			})
		}
	}

	return events
}

func mathRound(val float64, precision int) float64 {
	ratio := math.Pow(10, float64(precision))
	return math.Round(val*ratio) / ratio
}

func (srv *server) normalizeBehavioralSignals(ctx context.Context, signals BehavioralSignalsRequest, dbPolicyMode string) (map[string]any, error) {
	policyMode := "observe_only"
	if signals.PolicyMode != nil && *signals.PolicyMode != "" {
		policyMode = *signals.PolicyMode
	} else if dbPolicyMode != "" {
		policyMode = dbPolicyMode
	}
	if policyMode != "observe_only" && policyMode != "strict_flagging" {
		policyMode = "observe_only"
	}

	var normalizedEvents []ProctoringEvent
	for i, raw := range signals.Events {
		normalizedEvents = append(normalizedEvents, normalizeEvent(raw, i, policyMode))
	}

	synthesized := synthesizeEventsFromCounters(signals)
	existingTypes := make(map[string]bool)
	for _, item := range normalizedEvents {
		existingTypes[item.EventType] = true
	}

	for _, item := range synthesized {
		if !existingTypes[item.EventType] {
			normalized := normalizeEvent(item, len(normalizedEvents), policyMode)
			normalizedEvents = append(normalizedEvents, normalized)
			existingTypes[normalized.EventType] = true
		}
	}

	payload := map[string]any{
		"response_times":       signals.ResponseTimes,
		"paste_count":          signals.PasteCount,
		"tab_switches":         signals.TabSwitches,
		"face_away_pct":        signals.FaceAwayPct,
		"speech_activity_pct":  signals.SpeechActivityPct,
		"silence_pct":          signals.SilencePct,
		"long_silence_count":   signals.LongSilenceCount,
		"speech_segment_count": signals.SpeechSegmentCount,
		"policy_mode":          policyMode,
		"events":               normalizedEvents,
		"captured_at":          time.Now().UTC().Format(time.RFC3339),
	}

	return payload, nil
}

func (srv *server) handlePostSignals(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	interviewIDStr := strings.TrimSpace(r.PathValue("interview_id"))
	if _, err := uuid.Parse(interviewIDStr); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid interview id")
		return
	}

	var exists bool
	err = srv.db.QueryRow(r.Context(), "SELECT EXISTS(SELECT 1 FROM interviews WHERE id = $1 AND candidate_id = $2)", interviewIDStr, candidateID).Scan(&exists)
	if err != nil || !exists {
		writeError(w, http.StatusNotFound, "Interview not found.")
		return
	}

	var signals BehavioralSignalsRequest
	if err := json.NewDecoder(r.Body).Decode(&signals); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid request body")
		return
	}

	var dbPolicyMode string
	err = srv.db.QueryRow(r.Context(), "SELECT proctoring_policy_mode FROM platform_settings WHERE id = 1").Scan(&dbPolicyMode)
	if err != nil {
		dbPolicyMode = "observe_only"
	}

	normalized, err := srv.normalizeBehavioralSignals(r.Context(), signals, dbPolicyMode)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to normalize signals")
		return
	}

	normalizedJSON, err := json.Marshal(normalized)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to serialize signals")
		return
	}

	_, err = srv.db.Exec(r.Context(), "UPDATE interviews SET behavioral_signals = $1 WHERE id = $2 AND candidate_id = $3", normalizedJSON, interviewIDStr, candidateID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to persist behavioral signals")
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (srv *server) handlePostRecording(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	candidateID, err := srv.getCandidateContext(r.Context(), user)
	if err != nil {
		writeError(w, http.StatusForbidden, "Forbidden")
		return
	}

	interviewIDStr := strings.TrimSpace(r.PathValue("interview_id"))
	if _, err := uuid.Parse(interviewIDStr); err != nil {
		writeError(w, http.StatusBadRequest, "Invalid interview id")
		return
	}

	var exists bool
	err = srv.db.QueryRow(r.Context(), "SELECT EXISTS(SELECT 1 FROM interviews WHERE id = $1 AND candidate_id = $2)", interviewIDStr, candidateID).Scan(&exists)
	if err != nil || !exists {
		writeError(w, http.StatusNotFound, "Interview not found.")
		return
	}

	maxBytes := int64(250 * 1024 * 1024)
	if err := r.ParseMultipartForm(maxBytes); err != nil {
		writeError(w, http.StatusRequestEntityTooLarge, "Upload exceeds maximum allowed size.")
		return
	}

	file, header, err := r.FormFile("file")
	if err != nil {
		writeError(w, http.StatusBadRequest, "file field is required")
		return
	}
	defer file.Close()

	contentType := strings.ToLower(strings.TrimSpace(strings.Split(header.Header.Get("Content-Type"), ";")[0]))
	allowedTypes := map[string]string{
		"video/webm": ".webm",
		"video/mp4":  ".mp4",
	}
	ext, allowed := allowedTypes[contentType]
	if !allowed {
		writeError(w, http.StatusUnsupportedMediaType, "Unsupported recording format. Allowed: video/webm, video/mp4.")
		return
	}

	var recordingPath string
	if srv.config.MediaServiceURL != "" {
		recordingPath, err = srv.uploadToMediaService(interviewIDStr, file, contentType)
		if err == nil && recordingPath != "" {
			_, err = srv.db.Exec(r.Context(), "UPDATE interviews SET recording_path = $1 WHERE id = $2 AND candidate_id = $3", recordingPath, interviewIDStr, candidateID)
			if err != nil {
				writeError(w, http.StatusInternalServerError, "Failed to save recording metadata")
				return
			}
			w.WriteHeader(http.StatusNoContent)
			return
		}
		if seeker, ok := file.(io.ReadSeeker); ok {
			_, _ = seeker.Seek(0, io.SeekStart)
		}
	}

	recordingDir := filepath.Join(srv.storageDir, "..", "recordings")
	if err := os.MkdirAll(recordingDir, 0755); err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to prepare storage directory")
		return
	}

	recordingPath = filepath.Join(recordingDir, interviewIDStr+ext)
	out, err := os.Create(recordingPath)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to create local recording file")
		return
	}
	defer out.Close()

	written, err := io.Copy(out, file)
	if err != nil {
		_ = os.Remove(recordingPath)
		writeError(w, http.StatusInternalServerError, "Failed to write local recording file")
		return
	}

	if written > maxBytes {
		_ = os.Remove(recordingPath)
		writeError(w, http.StatusRequestEntityTooLarge, "Recording exceeds maximum allowed size.")
		return
	}

	_, err = srv.db.Exec(r.Context(), "UPDATE interviews SET recording_path = $1 WHERE id = $2 AND candidate_id = $3", recordingPath, interviewIDStr, candidateID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to save recording metadata")
		return
	}

	w.WriteHeader(http.StatusNoContent)
}

func (srv *server) uploadToMediaService(interviewID string, file multipart.File, contentType string) (string, error) {
	url := fmt.Sprintf("%s/v1/recordings/%s", strings.TrimSuffix(srv.config.MediaServiceURL, "/"), interviewID)
	
	req, err := http.NewRequest("POST", url, file)
	if err != nil {
		return "", err
	}
	req.Header.Set("Content-Type", contentType)

	client := &http.Client{Timeout: 120 * time.Second}
	resp, err := client.Do(req)
	if err != nil {
		return "", err
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		return "", fmt.Errorf("media service returned status %d", resp.StatusCode)
	}

	var res map[string]any
	if err := json.NewDecoder(resp.Body).Decode(&res); err != nil {
		return "", err
	}

	path, _ := res["path"].(string)
	if path == "" {
		return "", errors.New("media service returned empty path")
	}

	return path, nil
}
