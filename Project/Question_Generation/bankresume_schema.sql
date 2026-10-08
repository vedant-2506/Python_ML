-- RankResume core question bank schema. Safe to run in rankresume.
DO $$ BEGIN
    IF current_database() <> 'rankresume' THEN
        RAISE EXCEPTION 'Run this file against database rankresume';
    END IF;
END $$;

CREATE TABLE IF NOT EXISTS public.bankresume (
    question_id BIGSERIAL PRIMARY KEY,
    subject VARCHAR(100) NOT NULL,
    topic VARCHAR(200) NOT NULL,
    question TEXT NOT NULL,
    answer TEXT NOT NULL,
    expected_concepts TEXT NOT NULL,
    difficulty VARCHAR(20) NOT NULL CHECK (difficulty IN ('Easy', 'Medium', 'Hard')),
    question_hash CHAR(64) NOT NULL UNIQUE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS bankresume_subject_idx ON public.bankresume (subject);
CREATE INDEX IF NOT EXISTS bankresume_topic_idx ON public.bankresume (topic);
CREATE INDEX IF NOT EXISTS bankresume_difficulty_idx ON public.bankresume (difficulty);
