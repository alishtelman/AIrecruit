package main

import (
	"encoding/json"
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

func TestHandleStatusReturnsSafeDiagnostics(t *testing.T) {
	dir := t.TempDir()
	srv := &server{cfg: config{
		GroqAPIKey:          "groq-secret",
		ElevenLabsAPIKey:    "elevenlabs-secret",
		TTSProvider:         "groq",
		TTSFallbackProvider: "elevenlabs",
		ElevenLabsModel:     "eleven-model",
		RecordingDir:        dir,
		MaxRecordingBytes:   250 * 1024 * 1024,
	}}
	req := httptest.NewRequest(http.MethodGet, "/v1/status", nil)
	rec := httptest.NewRecorder()

	srv.handleStatus(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	body := rec.Body.String()
	if strings.Contains(body, dir) || strings.Contains(body, "groq-secret") || strings.Contains(body, "elevenlabs-secret") {
		t.Fatalf("status leaked unsafe data: %s", body)
	}
	var payload statusResponse
	if err := json.Unmarshal(rec.Body.Bytes(), &payload); err != nil {
		t.Fatal(err)
	}
	if payload.Service != "media-service" || payload.TTSProvider != "groq" || payload.TTSFallbackProvider != "elevenlabs" {
		t.Fatalf("unexpected provider status: %#v", payload)
	}
	if !payload.STTConfigured || payload.STTRequiredAPIKey != "GROQ_API_KEY" || payload.STTModel != groqSTTModel {
		t.Fatalf("unexpected stt status: %#v", payload)
	}
	if !payload.RecordingStorageConfigured || !payload.RecordingStorageWritable || payload.MaxRecordingSizeMB != 250 {
		t.Fatalf("unexpected recording status: %#v", payload)
	}
	if len(payload.RecordingAllowedContentType) != 2 || payload.RecordingAllowedContentType[0] != "video/mp4" {
		t.Fatalf("unexpected recording content types: %#v", payload.RecordingAllowedContentType)
	}
	if len(payload.TTSProviders) != 2 || payload.TTSProviders[0].RequiredAPIKey == "" {
		t.Fatalf("unexpected tts provider metadata: %#v", payload.TTSProviders)
	}
}

func TestHandleHealthReportsRecordingStorageWritable(t *testing.T) {
	srv := &server{cfg: config{RecordingDir: t.TempDir(), MaxRecordingBytes: 1024}}
	req := httptest.NewRequest(http.MethodGet, "/health", nil)
	rec := httptest.NewRecorder()

	srv.handleHealth(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"recording_storage_writable":true`) {
		t.Fatalf("expected writable health payload: %s", rec.Body.String())
	}
}

func TestStatusReportsUnconfiguredRecordingStorage(t *testing.T) {
	srv := &server{cfg: config{RecordingDir: "", MaxRecordingBytes: 1024}}
	status := srv.status()

	if status.RecordingStorageConfigured || status.RecordingStorageWritable {
		t.Fatalf("expected unconfigured storage to be unsafe: %#v", status)
	}
}
