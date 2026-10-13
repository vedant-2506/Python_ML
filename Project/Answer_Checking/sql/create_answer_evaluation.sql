CREATE TABLE IF NOT EXISTS public.answer_evaluation (
    evaluation_id BIGSERIAL PRIMARY KEY,
    candidate_id INTEGER,
    jd_id BIGINT NOT NULL,
    question_id BIGINT NOT NULL,
    expected_answer TEXT,
    candidate_answer TEXT,
    difficulty VARCHAR(50),
    max_marks NUMERIC(10, 2),
    expected_facts JSONB,
    semantic_score NUMERIC(5, 2),
    factual_correctness_score NUMERIC(5, 2),
    answer_score NUMERIC(5, 2),
    classification VARCHAR(30),
    obtained_marks NUMERIC(10, 2),
    evaluation_status VARCHAR(30) NOT NULL DEFAULT 'Pending',
    evaluation_notes TEXT,
    evaluated_at TIMESTAMPTZ DEFAULT NOW()
);

ALTER TABLE public.answer_evaluation
    ADD COLUMN IF NOT EXISTS candidate_id INTEGER;

ALTER TABLE public.answer_evaluation
    DROP COLUMN IF EXISTS attempt_id,
    DROP COLUMN IF EXISTS legacy_attempt_id;

ALTER TABLE public.answer_evaluation
    DROP COLUMN IF EXISTS first_six_average;

CREATE INDEX IF NOT EXISTS idx_answer_evaluation_jd_question
    ON public.answer_evaluation (jd_id, question_id);

DROP INDEX IF EXISTS public.idx_answer_evaluation_attempt_question;

CREATE INDEX IF NOT EXISTS idx_answer_evaluation_candidate_question
    ON public.answer_evaluation (candidate_id, jd_id, question_id, evaluation_id);

CREATE INDEX IF NOT EXISTS idx_answer_evaluation_status
    ON public.answer_evaluation (evaluation_status);

CREATE INDEX IF NOT EXISTS idx_answer_evaluation_question_id
    ON public.answer_evaluation (question_id);
