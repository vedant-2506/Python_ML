# RankResume Question Selection and Adaptive Generation

This folder implements only Phase 4 and Phase 5. It leaves `Question_Generation`, `bankresume`, ATS code, answer checking, and candidate ranking unchanged.

## Run the notebook

From the project root:

```bash
.venv/bin/jupyter nbconvert --to notebook --execute --inplace Question_Selection_Generation/Question_Selection_Generation.ipynb
```

The notebook uses existing JD `jd_id=5` by default, creates one isolated demo exam session, selects six Question Bank snapshots, checks adaptive boundary rules, calls Ollama `qwen3:8b`, validates four structured Changing-Tech questions, and stores them in `generated_questions` and `question_exam`.

## Modules

- `question_selector.py`: vocabulary-backed Core/Changing-Tech classification, 3 Easy + 2 Medium + 1 Hard selection, and adaptive thresholds.
- `llm_question_generator.py`: native Ollama HTTP client, JSON validation, answer sentence checks, duplicate checks, and idempotent storage.
- `exam_workflow.py`: one 30-minute exam session and stage mapping.
- `selection_generation_schema.sql`: additive tables only.
- `prompts/adaptive_question_prompt.py`: model prompt contract.

The database defaults are inherited from the existing `Question_Generation.database.connect()` helper. Override them with the existing `RANKRESUME_DB_*` variables or `OLLAMA_*` variables.
