-- Isolated schema for exam snapshots and adaptive questions.
-- Existing RankResume tables, including bankresume, are not altered.
CREATE TABLE IF NOT EXISTS public.exam_sessions (
    exam_id UUID PRIMARY KEY,
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id),
    started_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ends_at TIMESTAMP NOT NULL,
    duration_minutes SMALLINT NOT NULL DEFAULT 30 CHECK (duration_minutes = 30),
    status VARCHAR(30) NOT NULL DEFAULT 'STAGE1_READY'
        CHECK (status IN ('STAGE1_READY', 'STAGE1_SUBMITTED', 'STAGE2_READY', 'COMPLETED'))
);

CREATE TABLE IF NOT EXISTS public.generated_questions (
    generated_question_id BIGSERIAL PRIMARY KEY,
    exam_id UUID NOT NULL REFERENCES public.exam_sessions(exam_id),
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id),
    skill VARCHAR(200) NOT NULL,
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    expected_concepts JSONB NOT NULL,
    difficulty VARCHAR(20) NOT NULL CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    model_name VARCHAR(200) NOT NULL,
    question_hash CHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (exam_id, question_hash)
);

CREATE TABLE IF NOT EXISTS public.question_exam (
    exam_question_id BIGSERIAL PRIMARY KEY,
    exam_id UUID NOT NULL REFERENCES public.exam_sessions(exam_id),
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id),
    question_order SMALLINT NOT NULL CHECK (question_order BETWEEN 1 AND 10),
    stage SMALLINT NOT NULL CHECK (stage IN (1, 2)),
    source VARCHAR(20) NOT NULL CHECK (source IN ('Question Bank', 'LLM')),
    question_id BIGINT REFERENCES public.bankresume(question_id),
    generated_question_id BIGINT REFERENCES public.generated_questions(generated_question_id),
    question TEXT NOT NULL,
    reference_answer TEXT NOT NULL,
    expected_concepts JSONB NOT NULL,
    difficulty VARCHAR(20) NOT NULL CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    skill VARCHAR(200),
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (exam_id, question_order),
    CHECK ((source = 'Question Bank' AND question_id IS NOT NULL AND generated_question_id IS NULL)
        OR (source = 'LLM' AND question_id IS NULL AND generated_question_id IS NOT NULL))
);

CREATE INDEX IF NOT EXISTS generated_questions_exam_idx ON public.generated_questions (exam_id);
CREATE INDEX IF NOT EXISTS question_exam_exam_idx ON public.question_exam (exam_id, question_order);

-- Stage 1 is one six-question snapshot per session.  These indexes do not
-- prevent a Question Bank row from being reused by a different JD/session.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM public.question_exam
        WHERE stage = 1
        GROUP BY exam_id, question_id
        HAVING question_id IS NOT NULL AND COUNT(*) > 1
    ) THEN
        CREATE UNIQUE INDEX IF NOT EXISTS question_exam_stage1_question_uq
            ON public.question_exam (exam_id, question_id)
            WHERE stage = 1 AND question_id IS NOT NULL;
    ELSE
        RAISE NOTICE 'Skipped stage-1 question-id uniqueness index because existing duplicates require review';
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM public.question_exam
        WHERE stage = 1
        GROUP BY exam_id, lower(regexp_replace(trim(question), '\s+', ' ', 'g'))
        HAVING COUNT(*) > 1
    ) THEN
        CREATE UNIQUE INDEX IF NOT EXISTS question_exam_stage1_text_uq
            ON public.question_exam
            (exam_id, lower(regexp_replace(trim(question), '\s+', ' ', 'g')))
            WHERE stage = 1;
    ELSE
        RAISE NOTICE 'Skipped stage-1 text uniqueness index because existing duplicates require review';
    END IF;
END $$;
