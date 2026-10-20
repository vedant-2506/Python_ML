CREATE TABLE IF NOT EXISTS public.final_evaluation_result (
    exam_id UUID NOT NULL,
    jd_id BIGINT NOT NULL,
    candidate_id INTEGER NOT NULL,
    first_six_average NUMERIC(5, 2) NOT NULL,
    last_four_average NUMERIC(5, 2) NOT NULL,
    final_result NUMERIC(5, 2) NOT NULL,
    evaluation_status VARCHAR(30) NOT NULL DEFAULT 'Completed',
    calculated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT final_evaluation_result_exam_candidate_key
        UNIQUE (exam_id, candidate_id)
);
