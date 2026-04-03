import { getToken } from "./auth";
import type {
  ActiveResume,
  AnalyticsFunnel,
  AnalyticsOverview,
  AnalyticsSalary,
  AssessmentReport,
  CandidateDetail,
  CandidateActivity,
  CompanyCandidateSearchParams,
  CandidateListItem,
  CandidateNote,
  CandidateRegisterRequest,
  CandidateAccessRequest,
  CandidatePrivacy,
  CandidateWithUser,
  CompanyShortlist,
  CompanyAssessment,
  CompanyMember,
  CompanyRegisterRequest,
  CompanyRegisterResponse,
  CompanyShareAccessStatus,
  EmployeeInviteInfo,
  FinishInterviewResponse,
  HireOutcomeResponse,
  InterviewDetail,
  InterviewListItem,
  InterviewReportStatusResponse,
  InterviewReplay,
  InterviewTemplate,
  LoginRequest,
  ProctoringTimeline,
  ResumeTextResponse,
  ResumeUploadResponse,
  SharedCandidateProfile,
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

  const res = await fetch(`${BASE_URL}${path}`, { ...options, headers, credentials: "include" });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail ?? "Request failed");
  }

  if (res.status === 204 || res.headers.get("content-length") === "0") {
    return undefined as T;
  }

  return res.json() as Promise<T>;
}

function withQuery(path: string, params: Record<string, string | number | string[] | undefined | null>): string {
  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value == null || value === "") continue;
    if (Array.isArray(value)) {
      for (const item of value) {
        if (item) query.append(key, item);
      }
      continue;
    }
    query.set(key, String(value));
  }
  const suffix = query.toString();
  return suffix ? `${path}?${suffix}` : path;
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

  logout: () =>
    request<void>("/api/v1/auth/logout", {
      method: "POST",
    }),

  me: () => request<User>("/api/v1/auth/me"),

  meCandidate: () => request<CandidateWithUser>("/api/v1/auth/me/candidate"),

  changePassword: (data: { current_password: string; new_password: string }) =>
    request<void>("/api/v1/auth/change-password", {
      method: "POST",
      body: JSON.stringify(data),
    }),
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
  listCandidates: (params: CompanyCandidateSearchParams = {}) =>
    request<CandidateListItem[]>(
      withQuery("/api/v1/company/candidates", {
        q: params.q,
        role: params.role,
        skills: params.skills,
        min_score: params.min_score,
        recommendation: params.recommendation,
        salary_min: params.salary_min,
        salary_max: params.salary_max,
        hire_outcome: params.hire_outcome,
        shortlist_id: params.shortlist_id,
        sort: params.sort,
      })
    ),

  getCandidate: (candidateId: string) =>
    request<CandidateDetail>(`/api/v1/company/candidates/${candidateId}`),

  getReport: (reportId: string) =>
    request<AssessmentReport>(`/api/v1/company/reports/${reportId}`),

  getReportProctoringTimeline: (reportId: string) =>
    request<ProctoringTimeline>(`/api/v1/company/reports/${reportId}/proctoring-timeline`),

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
      body: JSON.stringify({ email, role: "recruiter" }),
    }),

  inviteMemberWithRole: (email: string, role: "recruiter" | "viewer") =>
    request<{ member: CompanyMember; temp_password: string | null }>("/api/v1/company/members/invite", {
      method: "POST",
      body: JSON.stringify({ email, role }),
    }),

  removeMember: (userId: string) =>
    request<void>(`/api/v1/company/members/${userId}`, { method: "DELETE" }),

  listAssessments: () =>
    request<CompanyAssessment[]>("/api/v1/company/assessments"),

  createAssessment: (data: {
    employee_email: string;
    employee_name: string;
    target_role: string;
    assessment_type?: "employee_internal" | "candidate_external";
    template_id?: string | null;
    deadline_at?: string | null;
    expires_at?: string | null;
    branding_name?: string | null;
    branding_logo_url?: string | null;
  }) =>
    request<CompanyAssessment>("/api/v1/company/assessments", {
      method: "POST",
      body: JSON.stringify(data),
    }),

  deleteAssessment: (id: string) =>
    request<void>(`/api/v1/company/assessments/${id}`, { method: "DELETE" }),

  listShortlists: () =>
    request<CompanyShortlist[]>("/api/v1/company/shortlists"),

  createShortlist: (name: string) =>
    request<CompanyShortlist>("/api/v1/company/shortlists", {
      method: "POST",
      body: JSON.stringify({ name }),
    }),

  deleteShortlist: (shortlistId: string) =>
    request<void>(`/api/v1/company/shortlists/${shortlistId}`, { method: "DELETE" }),

  addCandidateToShortlist: (shortlistId: string, candidateId: string) =>
    request<void>(`/api/v1/company/shortlists/${shortlistId}/candidates/${candidateId}`, {
      method: "POST",
    }),

  removeCandidateFromShortlist: (shortlistId: string, candidateId: string) =>
    request<void>(`/api/v1/company/shortlists/${shortlistId}/candidates/${candidateId}`, {
      method: "DELETE",
    }),

  setOutcome: (candidateId: string, outcome: string, notes?: string) =>
    request<HireOutcomeResponse>(`/api/v1/company/candidates/${candidateId}/outcome`, {
      method: "POST",
      body: JSON.stringify({ outcome, notes }),
    }),

  getOutcome: (candidateId: string) =>
    request<HireOutcomeResponse>(`/api/v1/company/candidates/${candidateId}/outcome`),

  listCandidateNotes: (candidateId: string) =>
    request<CandidateNote[]>(`/api/v1/company/candidates/${candidateId}/notes`),

  createCandidateNote: (candidateId: string, body: string) =>
    request<CandidateNote>(`/api/v1/company/candidates/${candidateId}/notes`, {
      method: "POST",
      body: JSON.stringify({ body }),
    }),

  listCandidateActivity: (candidateId: string) =>
    request<CandidateActivity[]>(`/api/v1/company/candidates/${candidateId}/activity`),

  getInterviewReplay: (interviewId: string) =>
    request<InterviewReplay>(`/api/v1/company/interviews/${interviewId}/replay`),

  getAnalyticsOverview: () =>
    request<AnalyticsOverview>("/api/v1/company/analytics/overview"),

  getAnalyticsFunnel: () =>
    request<AnalyticsFunnel>("/api/v1/company/analytics/funnel"),

  getAnalyticsSalary: (params: { role?: string; shortlist_id?: string } = {}) =>
    request<AnalyticsSalary>(
      withQuery("/api/v1/company/analytics/salary", {
        role: params.role,
        shortlist_id: params.shortlist_id,
      })
    ),

  getShareLinkAccessStatus: (shareToken: string) =>
    request<CompanyShareAccessStatus>(`/api/v1/company/share-links/${encodeURIComponent(shareToken)}`),

  requestShareLinkAccess: (shareToken: string) =>
    request<CompanyShareAccessStatus>(`/api/v1/company/share-links/${encodeURIComponent(shareToken)}/request-access`, {
      method: "POST",
    }),
};

// ── Employee Invites ──────────────────────────────────────────────────────────

export const employeeApi = {
  getInvite: (token: string) =>
    request<EmployeeInviteInfo>(`/api/v1/employee/invite/${token}`),

  startAssessment: (token: string, language: "ru" | "en") =>
    request<{ interview_id: string; assessment_id: string }>(`/api/v1/employee/invite/${token}/start`, {
      method: "POST",
      body: JSON.stringify({ language }),
    }),
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

  getPrivacy: () =>
    request<CandidatePrivacy>("/api/v1/candidate/privacy"),

  updatePrivacy: (visibility: CandidatePrivacy["visibility"]) =>
    request<CandidatePrivacy>("/api/v1/candidate/privacy", {
      method: "PATCH",
      body: JSON.stringify({ visibility }),
    }),

  listAccessRequests: () =>
    request<CandidateAccessRequest[]>("/api/v1/candidate/access-requests"),

  approveAccessRequest: (requestId: string) =>
    request<CandidateAccessRequest>(`/api/v1/candidate/access-requests/${requestId}/approve`, {
      method: "POST",
    }),

  denyAccessRequest: (requestId: string) =>
    request<CandidateAccessRequest>(`/api/v1/candidate/access-requests/${requestId}/deny`, {
      method: "POST",
    }),

  salaryBenchmark: (role: string) =>
    request<{ role: string; buckets: { score_range: string; median_min: number | null; median_max: number | null; count: number }[] }>(
      `/api/v1/candidate/salary/benchmark?role=${encodeURIComponent(role)}`
    ),

  getSharedProfile: (shareToken: string) =>
    request<SharedCandidateProfile>(`/api/v1/candidate/share/${encodeURIComponent(shareToken)}`),
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

  getReportStatus: (id: string) =>
    request<InterviewReportStatusResponse>(`/api/v1/interviews/${id}/report-status`),

  retryReport: (id: string) =>
    request<InterviewReportStatusResponse>(`/api/v1/interviews/${id}/report-retry`, {
      method: "POST",
    }),

  getDetail: (id: string) =>
    request<InterviewDetail>(`/api/v1/interviews/${id}`),

  submitSignals: (
    id: string,
    signals: {
      response_times: { q: number; seconds: number }[];
      paste_count: number;
      tab_switches: number;
      face_away_pct: number | null;
      events?: { event_type: string; severity?: "info" | "medium" | "high"; occurred_at?: string; source?: string; details?: Record<string, unknown> }[];
      policy_mode?: "observe_only" | "strict_flagging";
    },
  ) =>
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

// ── TTS ───────────────────────────────────────────────────────────────────────

export const ttsApi = {
  synthesize: async (text: string, language?: string): Promise<Blob> => {
    const token = getToken();
    const headers: Record<string, string> = { "Content-Type": "application/json" };
    if (token) headers["Authorization"] = `Bearer ${token}`;

    const res = await fetch(`${BASE_URL}/api/v1/tts`, {
      method: "POST",
      headers,
      credentials: "include",
      body: JSON.stringify({ text, language }),
    });
    if (!res.ok) {
      const error = await res.json().catch(() => ({ detail: "Request failed" }));
      throw new Error(error.detail ?? "Request failed");
    }
    return res.blob();
  },
};

// ── Report ────────────────────────────────────────────────────────────────────

export const reportApi = {
  getById: (reportId: string) =>
    request<AssessmentReport>(`/api/v1/reports/${reportId}`),
};
