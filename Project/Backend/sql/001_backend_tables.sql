-- Additive RankResume backend migration. Run against the existing rankresume DB.
CREATE TABLE IF NOT EXISTS public.company (
    comp_id SERIAL PRIMARY KEY,
    company_name VARCHAR(200) NOT NULL,
    email VARCHAR(320) UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    phone VARCHAR(40),
    industry VARCHAR(150),
    website VARCHAR(300),
    is_verified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE public.candidate ADD COLUMN IF NOT EXISTS comp_id INTEGER;
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS comp_id INTEGER;
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS department VARCHAR(150);
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS experience_level VARCHAR(100);
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS positions INTEGER;
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'Active';
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS top_n INTEGER;
ALTER TABLE public.job_description ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW();
ALTER TABLE public.question_exam ADD COLUMN IF NOT EXISTS max_marks NUMERIC(10,2);
UPDATE public.question_exam SET max_marks = CASE lower(difficulty)
    WHEN 'easy' THEN 6 WHEN 'medium' THEN 12 WHEN 'hard' THEN 18 ELSE 10 END
    WHERE max_marks IS NULL;

DO $$ BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'candidate_comp_id_fkey') THEN
        ALTER TABLE public.candidate ADD CONSTRAINT candidate_comp_id_fkey
            FOREIGN KEY (comp_id) REFERENCES public.company(comp_id);
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'job_description_comp_id_fkey') THEN
        ALTER TABLE public.job_description ADD CONSTRAINT job_description_comp_id_fkey
            FOREIGN KEY (comp_id) REFERENCES public.company(comp_id);
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.job_candidate (
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id) ON DELETE CASCADE,
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id) ON DELETE CASCADE,
    PRIMARY KEY (jd_id, candidate_id)
);

CREATE TABLE IF NOT EXISTS public.processing_job (
    job_id UUID PRIMARY KEY,
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id) ON DELETE CASCADE,
    comp_id INTEGER NOT NULL REFERENCES public.company(comp_id),
    stage VARCHAR(30) NOT NULL DEFAULT 'uploading',
    total_files INTEGER NOT NULL DEFAULT 0,
    processed INTEGER NOT NULL DEFAULT 0,
    failed INTEGER NOT NULL DEFAULT 0,
    message TEXT,
    started_at TIMESTAMPTZ,
    finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS public.exam_invitation (
    invitation_id BIGSERIAL PRIMARY KEY,
    exam_id UUID NOT NULL REFERENCES public.exam_sessions(exam_id),
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id),
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id),
    token_hash CHAR(64) UNIQUE NOT NULL,
    email_sent_at TIMESTAMPTZ,
    expires_at TIMESTAMPTZ NOT NULL,
    opened_at TIMESTAMPTZ,
    status VARCHAR(30) NOT NULL DEFAULT 'SENT',
    send_error TEXT
);

CREATE TABLE IF NOT EXISTS public.exam_integrity_event (
    event_id BIGSERIAL PRIMARY KEY,
    exam_id UUID NOT NULL REFERENCES public.exam_sessions(exam_id),
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id),
    question_order SMALLINT,
    event_type VARCHAR(30) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    meta JSONB NOT NULL DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS public.answer_typing_stats (
    exam_id UUID NOT NULL REFERENCES public.exam_sessions(exam_id),
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id),
    question_order SMALLINT NOT NULL,
    keystrokes INTEGER NOT NULL DEFAULT 0,
    backspaces INTEGER NOT NULL DEFAULT 0,
    paste_attempts INTEGER NOT NULL DEFAULT 0,
    avg_interkey_ms DOUBLE PRECISION,
    first_key_delay_ms DOUBLE PRECISION,
    total_typing_ms DOUBLE PRECISION,
    PRIMARY KEY (exam_id, candidate_id, question_order)
);

CREATE TABLE IF NOT EXISTS public.answer_draft (
    exam_id UUID NOT NULL REFERENCES public.exam_sessions(exam_id),
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id),
    question_order SMALLINT NOT NULL,
    text TEXT NOT NULL DEFAULT '',
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (exam_id, candidate_id, question_order)
);

CREATE INDEX IF NOT EXISTS candidate_comp_id_idx ON public.candidate(comp_id);
CREATE INDEX IF NOT EXISTS job_description_comp_id_idx ON public.job_description(comp_id);
CREATE INDEX IF NOT EXISTS exam_invitation_token_hash_idx ON public.exam_invitation(token_hash);
