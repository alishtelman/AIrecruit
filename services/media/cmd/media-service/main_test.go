package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestRecordingUploadStoresFile(t *testing.T) {
	dir := t.TempDir()
	srv := &server{cfg: config{RecordingDir: dir, MaxRecordingBytes: 1024}}

	req := httptest.NewRequest(http.MethodPost, "/v1/recordings/interview-1", strings.NewReader("recording-bytes"))
	req.Header.Set("Content-Type", "video/webm")
	req.SetPathValue("recording_id", "interview-1")
	rec := httptest.NewRecorder()

	srv.handleRecordingUpload(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	content, err := os.ReadFile(filepath.Join(dir, "interview-1.webm"))
	if err != nil {
		t.Fatalf("expected recording file: %v", err)
	}
	if string(content) != "recording-bytes" {
		t.Fatalf("unexpected recording content: %q", string(content))
	}
}

func TestRecordingUploadRejectsUnsupportedType(t *testing.T) {
	srv := &server{cfg: config{RecordingDir: t.TempDir(), MaxRecordingBytes: 1024}}
	req := httptest.NewRequest(http.MethodPost, "/v1/recordings/interview-1", strings.NewReader("recording-bytes"))
	req.Header.Set("Content-Type", "text/plain")
	req.SetPathValue("recording_id", "interview-1")
	rec := httptest.NewRecorder()

	srv.handleRecordingUpload(rec, req)

	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("expected status 415, got %d", rec.Code)
	}
}

func TestRecordingUploadRejectsOversizeFile(t *testing.T) {
	srv := &server{cfg: config{RecordingDir: t.TempDir(), MaxRecordingBytes: 4}}
	req := httptest.NewRequest(http.MethodPost, "/v1/recordings/interview-1", strings.NewReader("too-large"))
	req.Header.Set("Content-Type", "video/mp4")
	req.SetPathValue("recording_id", "interview-1")
	rec := httptest.NewRecorder()

	srv.handleRecordingUpload(rec, req)

	if rec.Code != http.StatusRequestEntityTooLarge {
		t.Fatalf("expected status 413, got %d: %s", rec.Code, rec.Body.String())
	}
}
