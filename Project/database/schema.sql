-- Clean-install schema orchestration for RankResume.
-- Run from psql while connected to rankresume:
--   psql -U root -d rankresume -f database/schema.sql
-- This file contains schema only; it does not load candidate, job, or question data.
\ir ../DB_Store/database_setup.sql
\ir ../Question_Generation/bankresume_schema.sql
\ir ../Question_Selection_Generation/selection_generation_schema.sql
\ir ../Answer_Checking/sql/create_answer_evaluation.sql
\ir ../Answer_Checking/sql/create_final_evaluation_result.sql
\ir ../Backend/sql/001_backend_tables.sql
\ir ../Backend/sql/002_shortlisting.sql
