-- Additive, repeatable migration for persisted recruiter selections.
CREATE TABLE IF NOT EXISTS public.job_shortlist (
    jd_id BIGINT NOT NULL REFERENCES public.job_description(jd_id) ON DELETE CASCADE,
    candidate_id BIGINT NOT NULL REFERENCES public.candidate(candidate_id) ON DELETE CASCADE,
    rank INTEGER NOT NULL CHECK (rank > 0),
    status VARCHAR(20) NOT NULL DEFAULT 'SELECTED',
    selected_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (jd_id, candidate_id)
);

CREATE INDEX IF NOT EXISTS job_shortlist_jd_rank_idx
    ON public.job_shortlist (jd_id, rank);
