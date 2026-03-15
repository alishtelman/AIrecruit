import { getToken } from "./auth";
import type {
  AssessmentReport,
  CandidateRegisterRequest,
  CandidateWithUser,
  FinishInterviewResponse,
  InterviewDetail,
  LoginRequest,
  ResumeUploadResponse,
  SendMessageRequest,
  SendMessageResponse,
  StartInterviewRequest,
  StartInterviewResponse,
  TokenResponse,
  User,
} from "./types";

const BASE_URL = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  const token = getToken();
  const headers: Record<string, string> = {
    ...(options.headers as Record<string, string>),
  };

  // Don't set Content-Type for FormData — browser sets it with boundary
  if (!(options.body instanceof FormData)) {
    headers["Content-Type"] = "application/json";
  }
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail ?? "Request failed");
  }

  return res.json() as Promise<T>;
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export const authApi = {
  register: (data: CandidateRegisterRequest) =>
    request<CandidateWithUser>("/api/v1/auth/candidate/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  login: (data: LoginRequest) =>
    request<TokenResponse>("/api/v1/auth/login", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  me: () => request<User>("/api/v1/auth/me"),

  meCandidate: () => request<CandidateWithUser>("/api/v1/auth/me/candidate"),
};

// ── Resume ────────────────────────────────────────────────────────────────────

export const resumeApi = {
  upload: (file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<ResumeUploadResponse>("/api/v1/candidate/resume/upload", {
      method: "POST",
      body: form,
    });
  },
};

// ── Interview ─────────────────────────────────────────────────────────────────

export const interviewApi = {
  start: (data: StartInterviewRequest) =>
    request<StartInterviewResponse>("/api/v1/interviews/start", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  sendMessage: (id: string, data: SendMessageRequest) =>
    request<SendMessageResponse>(`/api/v1/interviews/${id}/message`, {
      method: "POST",
      body: JSON.stringify(data),
    }),

  finish: (id: string) =>
    request<FinishInterviewResponse>(`/api/v1/interviews/${id}/finish`, {
      method: "POST",
    }),

  getDetail: (id: string) =>
    request<InterviewDetail>(`/api/v1/interviews/${id}`),
};

// ── Report ────────────────────────────────────────────────────────────────────

export const reportApi = {
  getById: (reportId: string) =>
    request<AssessmentReport>(`/api/v1/reports/${reportId}`),
};
