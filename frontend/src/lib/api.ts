import { getToken } from "./auth";
import type {
  ActiveResume,
  AssessmentReport,
  CandidateDetail,
  CandidateListItem,
  CandidateRegisterRequest,
  CandidateWithUser,
  CompanyRegisterRequest,
  CompanyRegisterResponse,
  FinishInterviewResponse,
  HireOutcomeResponse,
  InterviewDetail,
  InterviewListItem,
  InterviewReplay,
  InterviewTemplate,
  LoginRequest,
  ResumeTextResponse,
  ResumeUploadResponse,
  SendMessageRequest,
  SendMessageResponse,
  StartInterviewRequest,
  StartInterviewResponse,
  TokenResponse,
  User,
  CompanyAssessment,
  CompanyMember,
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

// ── Company Auth ──────────────────────────────────────────────────────────────

export const companyAuthApi = {
  register: (data: CompanyRegisterRequest) =>
    request<CompanyRegisterResponse>("/api/v1/auth/company/register", {
      method: "POST",
      body: JSON.stringify(data),
    }),
};

// ── Company Candidates ────────────────────────────────────────────────────────

export const companyApi = {
  listCandidates: () =>
    request<CandidateListItem[]>("/api/v1/company/candidates"),

  getCandidate: (candidateId: string) =>
    request<CandidateDetail>(`/api/v1/company/candidates/${candidateId}`),

  listTemplates: () =>
    request<InterviewTemplate[]>("/api/v1/company/templates"),

  createTemplate: (data: Omit<InterviewTemplate, "template_id" | "company_id" | "created_at">) =>
    request<InterviewTemplate>("/api/v1/company/templates", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteTemplate: (templateId: string) =>
    request<void>(`/api/v1/company/templates/${templateId}`, { method: "DELETE" }),

  listMembers: () =>
    request<CompanyMember[]>("/api/v1/company/members"),

  inviteMember: (email: string) =>
    request<{ member: CompanyMember; temp_password: string | null }>("/api/v1/company/members/invite", {
      method: "POST",
      body: JSON.stringify({ email }),
    }),

  removeMember: (userId: string) =>
    request<void>(`/api/v1/company/members/${userId}`, { method: "DELETE" }),

  listAssessments: () =>
    request<CompanyAssessment[]>("/api/v1/company/assessments"),

  createAssessment: (data: { employee_email: string; employee_name: string; target_role: string }) =>
    request<CompanyAssessment>("/api/v1/company/assessments", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteAssessment: (id: string) =>
    request<void>(`/api/v1/company/assessments/${id}`, { method: "DELETE" }),

  setOutcome: (candidateId: string, outcome: string, notes?: string) =>
    request<HireOutcomeResponse>(`/api/v1/company/candidates/${candidateId}/outcome`, {
      method: "POST",
      body: JSON.stringify({ outcome, notes }),
    }),

  getOutcome: (candidateId: string) =>
    request<HireOutcomeResponse>(`/api/v1/company/candidates/${candidateId}/outcome`),

  getInterviewReplay: (interviewId: string) =>
    request<InterviewReplay>(`/api/v1/company/interviews/${interviewId}/replay`),
};

// ── Public Templates ──────────────────────────────────────────────────────────

export const templateApi = {
  listPublic: () =>
    request<InterviewTemplate[]>("/api/v1/interviews/templates/public"),
};

// ── Candidate ─────────────────────────────────────────────────────────────────

export const candidateApi = {
  stats: () =>
    request<{ has_resume: boolean; interview_count: number; completed_count: number; latest_report_id: string | null }>(
      "/api/v1/candidate/stats"
    ),

  getResume: () =>
    request<ActiveResume | null>("/api/v1/candidate/resume"),

  getResumeText: () =>
    request<ResumeTextResponse>("/api/v1/candidate/resume/text"),

  getSalary: () =>
    request<{ salary_min: number | null; salary_max: number | null; salary_currency: string }>("/api/v1/candidate/salary"),

  updateSalary: (data: { salary_min: number | null; salary_max: number | null; currency: string }) =>
    request<{ salary_min: number | null; salary_max: number | null; salary_currency: string }>("/api/v1/candidate/salary", {
      method: "PATCH",
      body: JSON.stringify(data),
    }),

  salaryBenchmark: (role: string) =>
    request<{ role: string; buckets: { score_range: string; median_min: number | null; median_max: number | null; count: number }[] }>(
      `/api/v1/candidate/salary/benchmark?role=${encodeURIComponent(role)}`
    ),
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
  list: () =>
    request<InterviewListItem[]>("/api/v1/interviews/"),

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

  submitSignals: (id: string, signals: { response_times: { q: number; seconds: number }[]; paste_count: number; tab_switches: number; face_away_pct: number | null }) =>
    request<void>(`/api/v1/interviews/${id}/signals`, {
      method: "POST",
      body: JSON.stringify(signals),
    }),

  uploadRecording: (id: string, blob: Blob) => {
    const form = new FormData();
    form.append("file", blob, "recording.webm");
    return request<void>(`/api/v1/interviews/${id}/recording`, {
      method: "POST",
      body: form,
    });
  },
};

// ── STT ───────────────────────────────────────────────────────────────────────

export const sttApi = {
  transcribe: (blob: Blob): Promise<{ text: string }> => {
    const form = new FormData();
    form.append("file", blob, "audio.webm");
    return request<{ text: string }>("/api/v1/stt", { method: "POST", body: form });
  },
};

// ── Report ────────────────────────────────────────────────────────────────────

export const reportApi = {
  getById: (reportId: string) =>
    request<AssessmentReport>(`/api/v1/reports/${reportId}`),
};
