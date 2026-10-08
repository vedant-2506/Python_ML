CREATE TABLE IF NOT EXISTS public.answer_store (
    answer_id BIGSERIAL PRIMARY KEY,
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id),
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id),
    exam_question_id BIGINT NOT NULL REFERENCES public.question_exam(exam_question_id),
    can_answer TEXT NOT NULL,
    can_answer_vector DOUBLE PRECISION[] NOT NULL,
    semantic_score DOUBLE PRECISION NOT NULL CHECK (semantic_score BETWEEN 0 AND 100),
    concept_score DOUBLE PRECISION NOT NULL CHECK (concept_score BETWEEN 0 AND 100),
    completeness_score DOUBLE PRECISION NOT NULL CHECK (completeness_score BETWEEN 0 AND 100),
    marks DOUBLE PRECISION NOT NULL CHECK (marks BETWEEN 0 AND 100),
    submitted_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
    UNIQUE (candidate_id, exam_question_id)
);
CREATE INDEX IF NOT EXISTS answer_store_candidate_idx ON public.answer_store(candidate_id);