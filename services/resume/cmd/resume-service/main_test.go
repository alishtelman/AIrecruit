package main

import (
	"archive/zip"
	"bytes"
	"io"
	"mime/multipart"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
)

func TestProcessUploadStoresDOCXAndExtractsText(t *testing.T) {
	dir := t.TempDir()
	body, contentType := multipartBody(t, "resume.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document", minimalDOCX(t, "Hello", "World"))
	req := httptest.NewRequest(http.MethodPost, "/v1/resumes", body)
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()

	srv := &server{storageDir: dir, maxBytes: 10 * 1024 * 1024}
	srv.handleUpload(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("expected status 200, got %d: %s", rec.Code, rec.Body.String())
	}
	if !strings.Contains(rec.Body.String(), `"raw_text":"Hello\nWorld"`) {
		t.Fatalf("expected extracted text, got %s", rec.Body.String())
	}
	files, err := os.ReadDir(dir)
	if err != nil {
		t.Fatal(err)
	}
	if len(files) != 1 || filepath.Ext(files[0].Name()) != ".docx" {
		t.Fatalf("expected one docx file, got %#v", files)
	}
}

func TestHandleUploadRejectsUnsupportedContentType(t *testing.T) {
	body, contentType := multipartBody(t, "resume.txt", "text/plain", []byte("hello"))
	req := httptest.NewRequest(http.MethodPost, "/v1/resumes", body)
	req.Header.Set("Content-Type", contentType)
	rec := httptest.NewRecorder()

	srv := &server{storageDir: t.TempDir(), maxBytes: 10 * 1024 * 1024}
	srv.handleUpload(rec, req)

	if rec.Code != http.StatusUnsupportedMediaType {
		t.Fatalf("expected status 415, got %d", rec.Code)
	}
}

func TestExtractPDFTextIsBestEffort(t *testing.T) {
	text := extractPDFText([]byte("%PDF-1.4\nBT (Senior Go Engineer) Tj ET"))

	if text != "Senior Go Engineer" {
		t.Fatalf("unexpected pdf text: %q", text)
	}
}

func multipartBody(t *testing.T, filename string, contentType string, content []byte) (io.Reader, string) {
	t.Helper()
	var body bytes.Buffer
	writer := multipart.NewWriter(&body)
	part, err := writer.CreatePart(map[string][]string{
		"Content-Disposition": {`form-data; name="file"; filename="` + filename + `"`},
		"Content-Type":        {contentType},
	})
	if err != nil {
		t.Fatal(err)
	}
	if _, err := part.Write(content); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return &body, writer.FormDataContentType()
}

func minimalDOCX(t *testing.T, paragraphs ...string) []byte {
	t.Helper()
	var body bytes.Buffer
	writer := zip.NewWriter(&body)
	file, err := writer.Create("word/document.xml")
	if err != nil {
		t.Fatal(err)
	}
	var xmlBody strings.Builder
	xmlBody.WriteString(`<?xml version="1.0" encoding="UTF-8"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>`)
	for _, paragraph := range paragraphs {
		xmlBody.WriteString(`<w:p><w:r><w:t>`)
		xmlBody.WriteString(paragraph)
		xmlBody.WriteString(`</w:t></w:r></w:p>`)
	}
	xmlBody.WriteString(`</w:body></w:document>`)
	if _, err := file.Write([]byte(xmlBody.String())); err != nil {
		t.Fatal(err)
	}
	if err := writer.Close(); err != nil {
		t.Fatal(err)
	}
	return body.Bytes()
}
