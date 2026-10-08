# Answer Checking

This module evaluates a candidate answer against the immutable `question_exam` snapshot. It does not branch on `source`, so Question Bank and LLM exam questions use the same pipeline.

The default offline embedding backend is a deterministic hashed token and bigram vector. It is deliberately small and requires no download. A compatible local Gensim model can be loaded with `EmbeddingEngine.from_word2vec(path)`; vectors are mean-pooled across answer tokens and cached. This keeps Word2Vec training/loading separate from evaluation.

Scores are bounded to 0-100 and combine semantic similarity, expected-concept coverage, and completeness with configurable weights of 0.50, 0.30, and 0.20. `AnswerStore` persistence uses an idempotent schema and an upsert on `(candidate_id, exam_question_id)`.

Run the tests from the project root:

```text
PYTHONPATH=. .venv/bin/python -m unittest discover -s Answer_Checking/tests -v
```

The notebook uses live read-only sample queries and rolls back its answer/candidate storage demonstrations.