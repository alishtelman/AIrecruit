package main

import (
	"encoding/json"
	"net/http"
	"time"

	"github.com/google/uuid"
)

type ShareLinkAccessStatusResponse struct {
	CandidateID              uuid.UUID `json:"candidate_id"`
	FullName                 string    `json:"full_name"`
	RequestStatus            *string   `json:"request_status"`
	CanOpenCompanyWorkspace  bool      `json:"can_open_company_workspace"`
}

type ShareLinkRequestResponse struct {
	CandidateID              uuid.UUID `json:"candidate_id"`
	FullName                 string    `json:"full_name"`
	RequestStatus            string    `json:"request_status"`
	CanOpenCompanyWorkspace  bool      `json:"can_open_company_workspace"`
}

func (srv *server) handleGetCandidateAccessRequests(w http.ResponseWriter, r *http.Request) {
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

	query := `
		SELECT ar.id, ar.company_id, c.name, ar.requested_by_user_id, u.email, ar.status, ar.created_at, ar.updated_at
		FROM candidate_access_requests ar
		JOIN companies c ON c.id = ar.company_id
		LEFT JOIN users u ON u.id = ar.requested_by_user_id
		WHERE ar.candidate_id = $1
		ORDER BY ar.created_at DESC
	`
	rows, err := srv.db.Query(r.Context(), query, candidateID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to retrieve access requests")
		return
	}
	defer rows.Close()

	var requests []CandidateAccessRequestResponse
	for rows.Next() {
		var req CandidateAccessRequestResponse
		var email *string
		if err := rows.Scan(&req.RequestID, &req.CompanyID, &req.CompanyName, &req.RequestedByUserID, &email, &req.Status, &req.CreatedAt, &req.UpdatedAt); err == nil {
			req.RequestedByEmail = email
			requests = append(requests, req)
		}
	}
	if requests == nil {
		requests = []CandidateAccessRequestResponse{}
	}
	writeJSON(w, http.StatusOK, requests)
}

func (srv *server) handleRespondAccessRequest(w http.ResponseWriter, r *http.Request, approve bool) {
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

	requestID := r.PathValue("request_id")
	if requestID == "" {
		writeError(w, http.StatusBadRequest, "Missing request_id")
		return
	}

	var currentStatus string
	var companyID uuid.UUID
	err = srv.db.QueryRow(r.Context(), "SELECT status, company_id FROM candidate_access_requests WHERE id = $1 AND candidate_id = $2", requestID, candidateID).Scan(&currentStatus, &companyID)
	if err != nil {
		writeError(w, http.StatusNotFound, "Request not found")
		return
	}

	if currentStatus != "pending" {
		writeError(w, http.StatusBadRequest, "Access request is already processed")
		return
	}

	newStatus := "denied"
	activityType := "access_denied"
	summary := "Candidate denied workspace access"
	if approve {
		newStatus = "approved"
		activityType = "access_approved"
		summary = "Candidate approved workspace access"
	}

	now := time.Now().UTC()
	_, err = srv.db.Exec(r.Context(), "UPDATE candidate_access_requests SET status = $1, updated_at = $2 WHERE id = $3", newStatus, now, requestID)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to update request")
		return
	}

	// Log activity
	metaJSON, _ := json.Marshal(map[string]any{"access_request_id": requestID})
	_, err = srv.db.Exec(r.Context(), "INSERT INTO candidate_activities (id, company_id, candidate_id, activity_type, summary, metadata, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
		uuid.New(), companyID, candidateID, activityType, summary, metaJSON, now)

	// Fetch updated request
	var req CandidateAccessRequestResponse
	var email *string
	query := `
		SELECT ar.id, ar.company_id, c.name, ar.requested_by_user_id, u.email, ar.status, ar.created_at, ar.updated_at
		FROM candidate_access_requests ar
		JOIN companies c ON c.id = ar.company_id
		LEFT JOIN users u ON u.id = ar.requested_by_user_id
		WHERE ar.id = $1
	`
	err = srv.db.QueryRow(r.Context(), query, requestID).Scan(&req.RequestID, &req.CompanyID, &req.CompanyName, &req.RequestedByUserID, &email, &req.Status, &req.CreatedAt, &req.UpdatedAt)
	if err == nil {
		req.RequestedByEmail = email
	}

	writeJSON(w, http.StatusOK, req)
}

func (srv *server) handleApproveAccessRequest(w http.ResponseWriter, r *http.Request) {
	srv.handleRespondAccessRequest(w, r, true)
}

func (srv *server) handleDenyAccessRequest(w http.ResponseWriter, r *http.Request) {
	srv.handleRespondAccessRequest(w, r, false)
}

func (srv *server) getShareLinkAccessStatus(r *http.Request, shareToken string, companyID uuid.UUID) (candidateID uuid.UUID, fullName string, requestStatus *string, canOpen bool, err error) {
	err = srv.db.QueryRow(r.Context(), "SELECT id, full_name FROM candidates WHERE public_share_token = $1", shareToken).Scan(&candidateID, &fullName)
	if err != nil {
		return
	}

	err = srv.db.QueryRow(r.Context(), "SELECT status FROM candidate_access_requests WHERE candidate_id = $1 AND company_id = $2 ORDER BY created_at DESC LIMIT 1", candidateID, companyID).Scan(&requestStatus)
	if err != nil {
		err = nil // Not found is fine
	}

	if requestStatus != nil && *requestStatus == "approved" {
		canOpen = true
	} else {
		var visibility string
		_ = srv.db.QueryRow(r.Context(), "SELECT profile_visibility FROM candidates WHERE id = $1", candidateID).Scan(&visibility)
		if visibility == "marketplace" || visibility == "direct_link" {
			canOpen = true
		}
	}
	return
}

func (srv *server) handleGetShareLinkStatus(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	if user.CompanyID == nil {
		writeError(w, http.StatusForbidden, "User is not part of a company")
		return
	}

	shareToken := r.PathValue("share_token")
	if shareToken == "" {
		writeError(w, http.StatusBadRequest, "Missing share_token")
		return
	}

	candidateID, fullName, requestStatus, canOpen, err := srv.getShareLinkAccessStatus(r, shareToken, *user.CompanyID)
	if err != nil {
		writeError(w, http.StatusNotFound, "Share link not found")
		return
	}

	resp := ShareLinkAccessStatusResponse{
		CandidateID:             candidateID,
		FullName:                fullName,
		RequestStatus:           requestStatus,
		CanOpenCompanyWorkspace: canOpen,
	}
	writeJSON(w, http.StatusOK, resp)
}

func (srv *server) handleRequestShareLinkAccess(w http.ResponseWriter, r *http.Request) {
	user, err := srv.authenticateUser(r)
	if err != nil {
		writeError(w, http.StatusUnauthorized, "Unauthorized")
		return
	}
	if user.CompanyID == nil {
		writeError(w, http.StatusForbidden, "User is not part of a company")
		return
	}

	shareToken := r.PathValue("share_token")
	if shareToken == "" {
		writeError(w, http.StatusBadRequest, "Missing share_token")
		return
	}

	candidateID, fullName, requestStatus, canOpen, err := srv.getShareLinkAccessStatus(r, shareToken, *user.CompanyID)
	if err != nil {
		writeError(w, http.StatusNotFound, "Share link not found")
		return
	}

	if requestStatus != nil && *requestStatus == "pending" {
		writeError(w, http.StatusBadRequest, "Access request is already pending")
		return
	}
	if canOpen {
		writeError(w, http.StatusBadRequest, "Candidate profile is already accessible")
		return
	}

	now := time.Now().UTC()
	reqID := uuid.New()
	_, err = srv.db.Exec(r.Context(), "INSERT INTO candidate_access_requests (id, candidate_id, company_id, requested_by_user_id, status, created_at, updated_at) VALUES ($1, $2, $3, $4, $5, $6, $7)",
		reqID, candidateID, *user.CompanyID, user.ID, "pending", now, now)
	if err != nil {
		writeError(w, http.StatusInternalServerError, "Failed to create access request")
		return
	}

	// Log activity
	metaJSON, _ := json.Marshal(map[string]any{"access_request_id": reqID.String(), "status": "pending"})
	_, err = srv.db.Exec(r.Context(), "INSERT INTO candidate_activities (id, company_id, candidate_id, actor_user_id, activity_type, summary, metadata, created_at) VALUES ($1, $2, $3, $4, $5, $6, $7, $8)",
		uuid.New(), *user.CompanyID, candidateID, user.ID, "access_requested", "Requested candidate workspace access", metaJSON, now)

	resp := ShareLinkRequestResponse{
		CandidateID:             candidateID,
		FullName:                fullName,
		RequestStatus:           "pending",
		CanOpenCompanyWorkspace: false,
	}
	writeJSON(w, http.StatusOK, resp)
}
