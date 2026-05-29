--
-- PostgreSQL database dump
--

\restrict HXXDVvZQxsMKBAbhFqSbIi9LugB3FK4nFoMvsVVNdCoWAiXC4YE7bMyg854vcz8

-- Dumped from database version 16.13
-- Dumped by pg_dump version 16.13

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: admin_audit_logs; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.admin_audit_logs (
    id uuid NOT NULL,
    actor_user_id uuid NOT NULL,
    action character varying(120) NOT NULL,
    entity_type character varying(80) NOT NULL,
    entity_id character varying(120),
    summary text NOT NULL,
    metadata_json json,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.admin_audit_logs OWNER TO recruiting;

--
-- Name: alembic_version; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.alembic_version (
    version_num character varying(32) NOT NULL
);


ALTER TABLE public.alembic_version OWNER TO recruiting;

--
-- Name: assessment_reports; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.assessment_reports (
    id uuid NOT NULL,
    interview_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    overall_score double precision,
    hard_skills_score double precision,
    soft_skills_score double precision,
    communication_score double precision,
    strengths json NOT NULL,
    weaknesses json NOT NULL,
    recommendations json NOT NULL,
    hiring_recommendation character varying(50) NOT NULL,
    interview_summary text,
    full_report_json json NOT NULL,
    model_version character varying(100) DEFAULT ''::character varying NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    problem_solving_score double precision,
    competency_scores json,
    per_question_analysis json,
    skill_tags json,
    red_flags json,
    response_consistency double precision,
    cheat_risk_score double precision,
    cheat_flags json,
    overall_confidence double precision,
    competency_confidence json,
    confidence_reasons json,
    evidence_coverage json,
    decision_policy_version character varying(64)
);


ALTER TABLE public.assessment_reports OWNER TO recruiting;

--
-- Name: candidate_access_requests; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.candidate_access_requests (
    id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    company_id uuid NOT NULL,
    requested_by_user_id uuid,
    status character varying(32) NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.candidate_access_requests OWNER TO recruiting;

--
-- Name: candidate_skills; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.candidate_skills (
    id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    report_id uuid NOT NULL,
    skill_name character varying(200) NOT NULL,
    proficiency character varying(50) NOT NULL,
    evidence_summary text,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.candidate_skills OWNER TO recruiting;

--
-- Name: candidates; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.candidates (
    id uuid NOT NULL,
    user_id uuid NOT NULL,
    full_name character varying(255) NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    salary_min integer,
    salary_max integer,
    salary_currency character varying(10) DEFAULT 'USD'::character varying NOT NULL,
    profile_visibility character varying(32) DEFAULT 'marketplace'::character varying NOT NULL,
    public_share_token character varying(128)
);


ALTER TABLE public.candidates OWNER TO recruiting;

--
-- Name: companies; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.companies (
    id uuid NOT NULL,
    owner_user_id uuid,
    name character varying(255) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    ai_settings json
);


ALTER TABLE public.companies OWNER TO recruiting;

--
-- Name: company_assessments; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.company_assessments (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    created_by_user_id uuid NOT NULL,
    employee_email character varying(255) NOT NULL,
    employee_name character varying(255) NOT NULL,
    target_role character varying(100) NOT NULL,
    invite_token character varying(64) NOT NULL,
    status character varying(50) NOT NULL,
    interview_id uuid,
    created_at timestamp without time zone NOT NULL,
    assessment_type character varying(50) DEFAULT 'employee_internal'::character varying NOT NULL,
    template_id uuid,
    deadline_at timestamp without time zone,
    expires_at timestamp without time zone,
    opened_at timestamp without time zone,
    completed_at timestamp without time zone,
    branding_name character varying(255),
    branding_logo_url character varying(500),
    module_plan json,
    current_module_index integer DEFAULT 0 NOT NULL
);


ALTER TABLE public.company_assessments OWNER TO recruiting;

--
-- Name: company_candidate_activities; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.company_candidate_activities (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    actor_user_id uuid,
    activity_type character varying(100) NOT NULL,
    summary character varying(255) NOT NULL,
    metadata json,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.company_candidate_activities OWNER TO recruiting;

--
-- Name: company_candidate_notes; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.company_candidate_notes (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    author_user_id uuid,
    body text NOT NULL,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.company_candidate_notes OWNER TO recruiting;

--
-- Name: company_members; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.company_members (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    user_id uuid NOT NULL,
    role character varying(50) NOT NULL,
    invited_by_user_id uuid,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.company_members OWNER TO recruiting;

--
-- Name: company_shortlist_candidates; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.company_shortlist_candidates (
    id uuid NOT NULL,
    shortlist_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.company_shortlist_candidates OWNER TO recruiting;

--
-- Name: company_shortlists; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.company_shortlists (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    created_by_user_id uuid,
    name character varying(200) NOT NULL,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.company_shortlists OWNER TO recruiting;

--
-- Name: hire_outcomes; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.hire_outcomes (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    interview_id uuid,
    outcome character varying(50) NOT NULL,
    notes text,
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL
);


ALTER TABLE public.hire_outcomes OWNER TO recruiting;

--
-- Name: interview_messages; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.interview_messages (
    id uuid NOT NULL,
    interview_id uuid NOT NULL,
    role character varying(50) NOT NULL,
    content text NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.interview_messages OWNER TO recruiting;

--
-- Name: interview_templates; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.interview_templates (
    id uuid NOT NULL,
    company_id uuid NOT NULL,
    name character varying(200) NOT NULL,
    target_role character varying(100) NOT NULL,
    questions json NOT NULL,
    description text,
    is_public boolean NOT NULL,
    created_at timestamp without time zone NOT NULL
);


ALTER TABLE public.interview_templates OWNER TO recruiting;

--
-- Name: interviews; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.interviews (
    id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    resume_id uuid,
    status character varying(50) DEFAULT 'created'::character varying NOT NULL,
    target_role character varying(100) NOT NULL,
    question_count integer DEFAULT 0 NOT NULL,
    max_questions integer DEFAULT 8 NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL,
    started_at timestamp without time zone,
    completed_at timestamp without time zone,
    template_id uuid,
    language character varying(10) DEFAULT 'ru'::character varying NOT NULL,
    recording_path character varying(500),
    company_assessment_id uuid,
    behavioral_signals json,
    followup_depth integer DEFAULT 0 NOT NULL,
    interview_state json,
    seniority_level character varying(20)
);


ALTER TABLE public.interviews OWNER TO recruiting;

--
-- Name: platform_settings; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.platform_settings (
    id integer NOT NULL,
    candidate_registration_enabled boolean DEFAULT true NOT NULL,
    company_registration_enabled boolean DEFAULT true NOT NULL,
    employee_invites_enabled boolean DEFAULT true NOT NULL,
    maintenance_mode_enabled boolean DEFAULT false NOT NULL,
    proctoring_policy_mode character varying(64),
    interviewer_model_preference character varying(120),
    assessor_model_preference character varying(120),
    created_at timestamp without time zone NOT NULL,
    updated_at timestamp without time zone NOT NULL,
    llm_provider character varying(32),
    interviewer_model character varying(160),
    assessor_model character varying(160),
    interviewer_prompt_override text,
    assessor_prompt_override text,
    llm_timeout_seconds integer,
    llm_max_retries integer
);


ALTER TABLE public.platform_settings OWNER TO recruiting;

--
-- Name: platform_settings_id_seq; Type: SEQUENCE; Schema: public; Owner: recruiting
--

CREATE SEQUENCE public.platform_settings_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.platform_settings_id_seq OWNER TO recruiting;

--
-- Name: platform_settings_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: recruiting
--

ALTER SEQUENCE public.platform_settings_id_seq OWNED BY public.platform_settings.id;


--
-- Name: resumes; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.resumes (
    id uuid NOT NULL,
    candidate_id uuid NOT NULL,
    file_name character varying(255) NOT NULL,
    file_path character varying(500) NOT NULL,
    file_size integer NOT NULL,
    raw_text text,
    parsed_json json,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.resumes OWNER TO recruiting;

--
-- Name: users; Type: TABLE; Schema: public; Owner: recruiting
--

CREATE TABLE public.users (
    id uuid NOT NULL,
    email character varying(255) NOT NULL,
    hashed_password character varying(255) NOT NULL,
    role character varying(50) NOT NULL,
    is_active boolean DEFAULT true NOT NULL,
    created_at timestamp without time zone DEFAULT now() NOT NULL,
    updated_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.users OWNER TO recruiting;

--
-- Name: platform_settings id; Type: DEFAULT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.platform_settings ALTER COLUMN id SET DEFAULT nextval('public.platform_settings_id_seq'::regclass);


--
-- Name: admin_audit_logs admin_audit_logs_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.admin_audit_logs
    ADD CONSTRAINT admin_audit_logs_pkey PRIMARY KEY (id);


--
-- Name: alembic_version alembic_version_pkc; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.alembic_version
    ADD CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num);


--
-- Name: assessment_reports assessment_reports_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.assessment_reports
    ADD CONSTRAINT assessment_reports_pkey PRIMARY KEY (id);


--
-- Name: candidate_access_requests candidate_access_requests_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_access_requests
    ADD CONSTRAINT candidate_access_requests_pkey PRIMARY KEY (id);


--
-- Name: candidate_skills candidate_skills_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_skills
    ADD CONSTRAINT candidate_skills_pkey PRIMARY KEY (id);


--
-- Name: candidates candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_pkey PRIMARY KEY (id);


--
-- Name: companies companies_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_pkey PRIMARY KEY (id);


--
-- Name: company_assessments company_assessments_invite_token_key; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_assessments
    ADD CONSTRAINT company_assessments_invite_token_key UNIQUE (invite_token);


--
-- Name: company_assessments company_assessments_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_assessments
    ADD CONSTRAINT company_assessments_pkey PRIMARY KEY (id);


--
-- Name: company_candidate_activities company_candidate_activities_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_activities
    ADD CONSTRAINT company_candidate_activities_pkey PRIMARY KEY (id);


--
-- Name: company_candidate_notes company_candidate_notes_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_notes
    ADD CONSTRAINT company_candidate_notes_pkey PRIMARY KEY (id);


--
-- Name: company_members company_members_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_members
    ADD CONSTRAINT company_members_pkey PRIMARY KEY (id);


--
-- Name: company_shortlist_candidates company_shortlist_candidates_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlist_candidates
    ADD CONSTRAINT company_shortlist_candidates_pkey PRIMARY KEY (id);


--
-- Name: company_shortlists company_shortlists_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlists
    ADD CONSTRAINT company_shortlists_pkey PRIMARY KEY (id);


--
-- Name: hire_outcomes hire_outcomes_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.hire_outcomes
    ADD CONSTRAINT hire_outcomes_pkey PRIMARY KEY (id);


--
-- Name: interview_messages interview_messages_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interview_messages
    ADD CONSTRAINT interview_messages_pkey PRIMARY KEY (id);


--
-- Name: interview_templates interview_templates_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interview_templates
    ADD CONSTRAINT interview_templates_pkey PRIMARY KEY (id);


--
-- Name: interviews interviews_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interviews
    ADD CONSTRAINT interviews_pkey PRIMARY KEY (id);


--
-- Name: platform_settings platform_settings_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.platform_settings
    ADD CONSTRAINT platform_settings_pkey PRIMARY KEY (id);


--
-- Name: resumes resumes_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.resumes
    ADD CONSTRAINT resumes_pkey PRIMARY KEY (id);


--
-- Name: candidate_access_requests uq_candidate_access_request_candidate_company; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_access_requests
    ADD CONSTRAINT uq_candidate_access_request_candidate_company UNIQUE (candidate_id, company_id);


--
-- Name: candidates uq_candidates_public_share_token; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT uq_candidates_public_share_token UNIQUE (public_share_token);


--
-- Name: candidates uq_candidates_user_id; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT uq_candidates_user_id UNIQUE (user_id);


--
-- Name: company_members uq_company_member; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_members
    ADD CONSTRAINT uq_company_member UNIQUE (company_id, user_id);


--
-- Name: company_shortlists uq_company_shortlist_name; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlists
    ADD CONSTRAINT uq_company_shortlist_name UNIQUE (company_id, name);


--
-- Name: hire_outcomes uq_hire_outcome_company_candidate; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.hire_outcomes
    ADD CONSTRAINT uq_hire_outcome_company_candidate UNIQUE (company_id, candidate_id);


--
-- Name: assessment_reports uq_reports_interview_id; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.assessment_reports
    ADD CONSTRAINT uq_reports_interview_id UNIQUE (interview_id);


--
-- Name: company_shortlist_candidates uq_shortlist_candidate; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlist_candidates
    ADD CONSTRAINT uq_shortlist_candidate UNIQUE (shortlist_id, candidate_id);


--
-- Name: interview_templates uq_template_company_name; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interview_templates
    ADD CONSTRAINT uq_template_company_name UNIQUE (company_id, name);


--
-- Name: users uq_users_email; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT uq_users_email UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: ix_assessment_reports_candidate_created_id_desc; Type: INDEX; Schema: public; Owner: recruiting
--

CREATE INDEX ix_assessment_reports_candidate_created_id_desc ON public.assessment_reports USING btree (candidate_id, created_at DESC, id DESC);


--
-- Name: ix_candidate_skills_candidate_created; Type: INDEX; Schema: public; Owner: recruiting
--

CREATE INDEX ix_candidate_skills_candidate_created ON public.candidate_skills USING btree (candidate_id, created_at DESC);


--
-- Name: ix_candidates_profile_visibility_id; Type: INDEX; Schema: public; Owner: recruiting
--

CREATE INDEX ix_candidates_profile_visibility_id ON public.candidates USING btree (profile_visibility, id);


--
-- Name: ix_company_shortlist_candidates_candidate_id; Type: INDEX; Schema: public; Owner: recruiting
--

CREATE INDEX ix_company_shortlist_candidates_candidate_id ON public.company_shortlist_candidates USING btree (candidate_id);


--
-- Name: ix_company_shortlists_company_id; Type: INDEX; Schema: public; Owner: recruiting
--

CREATE INDEX ix_company_shortlists_company_id ON public.company_shortlists USING btree (company_id);


--
-- Name: ix_interviews_marketplace_snapshot; Type: INDEX; Schema: public; Owner: recruiting
--

CREATE INDEX ix_interviews_marketplace_snapshot ON public.interviews USING btree (company_assessment_id, target_role, completed_at DESC, candidate_id);


--
-- Name: admin_audit_logs admin_audit_logs_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.admin_audit_logs
    ADD CONSTRAINT admin_audit_logs_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: assessment_reports assessment_reports_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.assessment_reports
    ADD CONSTRAINT assessment_reports_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: assessment_reports assessment_reports_interview_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.assessment_reports
    ADD CONSTRAINT assessment_reports_interview_id_fkey FOREIGN KEY (interview_id) REFERENCES public.interviews(id) ON DELETE CASCADE;


--
-- Name: candidate_access_requests candidate_access_requests_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_access_requests
    ADD CONSTRAINT candidate_access_requests_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: candidate_access_requests candidate_access_requests_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_access_requests
    ADD CONSTRAINT candidate_access_requests_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: candidate_access_requests candidate_access_requests_requested_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_access_requests
    ADD CONSTRAINT candidate_access_requests_requested_by_user_id_fkey FOREIGN KEY (requested_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: candidate_skills candidate_skills_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_skills
    ADD CONSTRAINT candidate_skills_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: candidate_skills candidate_skills_report_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidate_skills
    ADD CONSTRAINT candidate_skills_report_id_fkey FOREIGN KEY (report_id) REFERENCES public.assessment_reports(id) ON DELETE CASCADE;


--
-- Name: candidates candidates_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.candidates
    ADD CONSTRAINT candidates_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: companies companies_owner_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.companies
    ADD CONSTRAINT companies_owner_user_id_fkey FOREIGN KEY (owner_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_assessments company_assessments_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_assessments
    ADD CONSTRAINT company_assessments_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: company_assessments company_assessments_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_assessments
    ADD CONSTRAINT company_assessments_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: company_assessments company_assessments_interview_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_assessments
    ADD CONSTRAINT company_assessments_interview_id_fkey FOREIGN KEY (interview_id) REFERENCES public.interviews(id) ON DELETE SET NULL;


--
-- Name: company_candidate_activities company_candidate_activities_actor_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_activities
    ADD CONSTRAINT company_candidate_activities_actor_user_id_fkey FOREIGN KEY (actor_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_candidate_activities company_candidate_activities_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_activities
    ADD CONSTRAINT company_candidate_activities_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: company_candidate_activities company_candidate_activities_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_activities
    ADD CONSTRAINT company_candidate_activities_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: company_candidate_notes company_candidate_notes_author_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_notes
    ADD CONSTRAINT company_candidate_notes_author_user_id_fkey FOREIGN KEY (author_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_candidate_notes company_candidate_notes_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_notes
    ADD CONSTRAINT company_candidate_notes_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: company_candidate_notes company_candidate_notes_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_candidate_notes
    ADD CONSTRAINT company_candidate_notes_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: company_members company_members_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_members
    ADD CONSTRAINT company_members_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: company_members company_members_invited_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_members
    ADD CONSTRAINT company_members_invited_by_user_id_fkey FOREIGN KEY (invited_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_members company_members_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_members
    ADD CONSTRAINT company_members_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: company_shortlist_candidates company_shortlist_candidates_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlist_candidates
    ADD CONSTRAINT company_shortlist_candidates_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: company_shortlist_candidates company_shortlist_candidates_shortlist_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlist_candidates
    ADD CONSTRAINT company_shortlist_candidates_shortlist_id_fkey FOREIGN KEY (shortlist_id) REFERENCES public.company_shortlists(id) ON DELETE CASCADE;


--
-- Name: company_shortlists company_shortlists_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlists
    ADD CONSTRAINT company_shortlists_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: company_shortlists company_shortlists_created_by_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_shortlists
    ADD CONSTRAINT company_shortlists_created_by_user_id_fkey FOREIGN KEY (created_by_user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: company_assessments fk_company_assessments_template_id; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.company_assessments
    ADD CONSTRAINT fk_company_assessments_template_id FOREIGN KEY (template_id) REFERENCES public.interview_templates(id) ON DELETE SET NULL;


--
-- Name: interviews fk_interviews_template_id; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interviews
    ADD CONSTRAINT fk_interviews_template_id FOREIGN KEY (template_id) REFERENCES public.interview_templates(id) ON DELETE SET NULL;


--
-- Name: hire_outcomes hire_outcomes_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.hire_outcomes
    ADD CONSTRAINT hire_outcomes_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: hire_outcomes hire_outcomes_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.hire_outcomes
    ADD CONSTRAINT hire_outcomes_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: hire_outcomes hire_outcomes_interview_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.hire_outcomes
    ADD CONSTRAINT hire_outcomes_interview_id_fkey FOREIGN KEY (interview_id) REFERENCES public.interviews(id) ON DELETE SET NULL;


--
-- Name: interview_messages interview_messages_interview_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interview_messages
    ADD CONSTRAINT interview_messages_interview_id_fkey FOREIGN KEY (interview_id) REFERENCES public.interviews(id) ON DELETE CASCADE;


--
-- Name: interview_templates interview_templates_company_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interview_templates
    ADD CONSTRAINT interview_templates_company_id_fkey FOREIGN KEY (company_id) REFERENCES public.companies(id) ON DELETE CASCADE;


--
-- Name: interviews interviews_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interviews
    ADD CONSTRAINT interviews_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- Name: interviews interviews_company_assessment_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interviews
    ADD CONSTRAINT interviews_company_assessment_id_fkey FOREIGN KEY (company_assessment_id) REFERENCES public.company_assessments(id) ON DELETE SET NULL;


--
-- Name: interviews interviews_resume_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.interviews
    ADD CONSTRAINT interviews_resume_id_fkey FOREIGN KEY (resume_id) REFERENCES public.resumes(id) ON DELETE SET NULL;


--
-- Name: resumes resumes_candidate_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: recruiting
--

ALTER TABLE ONLY public.resumes
    ADD CONSTRAINT resumes_candidate_id_fkey FOREIGN KEY (candidate_id) REFERENCES public.candidates(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict HXXDVvZQxsMKBAbhFqSbIi9LugB3FK4nFoMvsVVNdCoWAiXC4YE7bMyg854vcz8

