"""Comprehensive tests for the repaired RankResume 10-question assessment workflow."""
from __future__ import annotations

import io
import unittest
import uuid
from contextlib import redirect_stdout
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from Answer_Checking.database import (
    calculate_first_six_average,
    get_candidate_exam_ids,
    get_first_six_average,
    get_question_details,
    save_candidate_answer,
    update_exam_session_status,
)
from Answer_Checking.manual_answer_input import (
    _collect_stage1,
    _collect_stage2,
    _load_or_create_exam,
    _validate_jd_and_candidate,
    _verify_completed_exam,
    main,
)
from Question_Selection_Generation.adaptive_policy import (
    calculate_percentage,
    determine_stage2_difficulty,
    resolve_stage2_difficulty,
)
from Question_Selection_Generation.exam_workflow import (
    _has_submitted_answers,
    select_questions,
)
from Question_Selection_Generation.groq_client import GroqError, generate_json
from Question_Selection_Generation.llm_question_generator import (
    GeneratedQuestion,
    validate_generated_questions,
)
from Question_Selection_Generation.question_selector import (
    SelectedQuestion,
    classify_skills,
    select_stage1_questions,
    validate_stage1_questions,
)


class TestWorkflowComprehensive(unittest.TestCase):
    def test_stage1_selection_exact_distribution(self):
        """Verifies that 3 Easy, 2 Medium, 1 Hard are selected from questions."""
        questions = [
            SelectedQuestion(1, "Python", "basics", "Q1", "A1", "C1", "Easy"),
            SelectedQuestion(2, "Python", "basics", "Q2", "A2", "C2", "Easy"),
            SelectedQuestion(3, "Python", "basics", "Q3", "A3", "C3", "Easy"),
            SelectedQuestion(4, "Python", "oop", "Q4", "A4", "C4", "Medium"),
            SelectedQuestion(5, "Python", "oop", "Q5", "A5", "C5", "Medium"),
            SelectedQuestion(6, "Python", "advanced", "Q6", "A6", "C6", "Hard"),
        ]
        errors = validate_stage1_questions(questions)
        self.assertEqual(errors, [])

    def test_stage1_selection_rejects_invalid_distribution(self):
        """Rejects distributions that do not match 3 Easy / 2 Medium / 1 Hard."""
        questions = [
            SelectedQuestion(i, "Python", "basics", f"Q{i}", "A", "C", "Easy")
            for i in range(1, 7)
        ]
        errors = validate_stage1_questions(questions)
        self.assertTrue(any("invalid difficulty distribution" in e for e in errors))

    def test_stage1_selection_rejects_duplicate_ids_or_text(self):
        """Rejects duplicates in bank selection."""
        questions = [
            SelectedQuestion(1, "Python", "basics", "Q1", "A", "C", "Easy"),
            SelectedQuestion(1, "Python", "basics", "Q2", "A", "C", "Easy"),
            SelectedQuestion(3, "Python", "basics", "Q3", "A", "C", "Easy"),
            SelectedQuestion(4, "Python", "oop", "Q4", "A", "C", "Medium"),
            SelectedQuestion(5, "Python", "oop", "Q5", "A", "C", "Medium"),
            SelectedQuestion(6, "Python", "advanced", "Q6", "A", "C", "Hard"),
        ]
        errors = validate_stage1_questions(questions)
        self.assertIn("duplicate Question Bank IDs", errors)

    def test_has_submitted_answers_checks_answer_evaluation(self):
        """Ensures _has_submitted_answers queries public.answer_evaluation."""
        class MockCursor:
            def __init__(self):
                self.query = ""
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, query, params=None):
                self.query = query
            def fetchone(self):
                return (True,)

        mock_conn = MagicMock()
        cursor = MockCursor()
        mock_conn.cursor.return_value = cursor

        result = _has_submitted_answers(mock_conn, uuid.uuid4())
        self.assertTrue(result)
        self.assertIn("FROM public.answer_evaluation", cursor.query)
        self.assertNotIn("answer_store", cursor.query)

    def test_stage1_stage2_numeric_id_collision_handling(self):
        """Ensures identical numeric IDs across Stage 1 and Stage 2 do not collide."""
        exam_id = str(uuid.uuid4())

        class CollisionCursor:
            def __init__(self):
                self.executed = []
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def execute(self, query, params=None):
                self.executed.append((query, params))
            def fetchone(self):
                # When checking ai_question_exam or question_exam
                last_q = self.executed[-1][0]
                if "FROM public.ai_question_exam" in last_q:
                    return (2, 5, "Generated Q5", "Ref answer", ["c1"], "Medium", "Machine Learning", 5)
                if "FROM public.question_exam" in last_q and "stage = 1" in last_q:
                    return (2, 5, "Bank Q5", "Ref answer", ["c1"], "Easy", "Python", 5)
                return None

        conn = MagicMock()
        conn.cursor.return_value = CollisionCursor()

        with patch("Answer_Checking.database.get_database_connection", return_value=conn):
            # Stage 1 question with ID 5
            q1_detail = get_question_details(2, 5, exam_id=exam_id, question_source="Question Bank")
            self.assertEqual(q1_detail["question"], "Bank Q5")
            self.assertEqual(q1_detail["question_source"], "Question Bank")

            # Stage 2 question with ID 5
            q2_detail = get_question_details(2, 5, exam_id=exam_id, question_source="groq_llm")
            self.assertEqual(q2_detail["question"], "Generated Q5")
            self.assertEqual(q2_detail["question_source"], "groq_llm")

    def test_stage2_collection_does_not_skip_colliding_stage1_id(self):
        """When an AI question has the same numeric ID as a Stage 1 question, it must not be skipped."""
        exam_id = str(uuid.uuid4())
        # Candidate has answered Stage 1 question ID 5
        existing_rows = [
            {"evaluation_id": 1, "question_id": 5, "question_source": "Question Bank", "evaluation_status": "Completed"}
        ]
        stage2_questions = [
            {"ai_question_exam_id": 5, "question_order": 1, "difficulty": "Easy", "question": "AI Question 1"}
        ]

        with patch("Answer_Checking.manual_answer_input.get_exam_evaluation_rows", return_value=existing_rows):
            with patch("Answer_Checking.manual_answer_input.collect_multiline_answer", return_value="candidate answer"):
                with patch("Answer_Checking.manual_answer_input.save_candidate_answer") as mock_save:
                    buffer = io.StringIO()
                    with redirect_stdout(buffer):
                        _collect_stage2(2, 1, exam_id, stage2_questions)
                    # Must be saved despite Stage 1 having question_id=5!
                    mock_save.assert_called_once_with(2, 5, "candidate answer", 1, exam_id)

    def test_multiple_candidate_attempts_rejected_without_exam_id(self):
        """Multiple attempts require explicit --exam-id."""
        with patch("Answer_Checking.manual_answer_input.get_candidate_exam_ids", return_value=["uuid-1", "uuid-2"]):
            with self.assertRaisesRegex(ValueError, "multiple candidate attempts exist"):
                _load_or_create_exam(2, 1, explicit_exam_id=None)

    def test_multiple_candidate_attempts_allowed_with_explicit_exam_id(self):
        """Supplying --exam-id disambiguates multiple candidate attempts safely."""
        with patch("Answer_Checking.manual_answer_input.get_candidate_exam_ids", return_value=["uuid-1", "uuid-2"]):
            with patch("Answer_Checking.manual_answer_input.get_stage1_questions", return_value=[{"question_id": i, "question": f"Q{i}"} for i in range(1, 7)]):
                exam_id, questions = _load_or_create_exam(2, 1, explicit_exam_id="uuid-2")
                self.assertEqual(exam_id, "uuid-2")
                self.assertEqual(len(questions), 6)

    def test_missing_llm_api_key_raises_groq_error(self):
        """Groq client fails with clear error when key is missing."""
        with patch("Question_Selection_Generation.groq_client.GROQ_API_KEY", ""):
            with self.assertRaises(GroqError) as ctx:
                generate_json("prompt")
            self.assertIn("GROQ_API_KEY is not configured", str(ctx.exception))

    def test_final_verification_requires_exact_counts(self):
        """_verify_completed_exam checks for 10 answers (6 Stage 1 and 4 Stage 2)."""
        incomplete_rows = [
            {"evaluation_id": i, "question_id": i, "question_source": "Question Bank", "evaluation_status": "Completed"}
            for i in range(1, 9)  # only 8 answers
        ]
        with patch("Answer_Checking.manual_answer_input.get_exam_evaluation_rows", return_value=incomplete_rows):
            with self.assertRaises(Exception) as ctx:
                _verify_completed_exam("exam-uuid", 1, 2)
            self.assertIn("expected 6 Stage 1 and 4 Stage 2 answers (total 10)", str(ctx.exception))

    def test_final_verification_succeeds_with_ten_answers(self):
        """_verify_completed_exam passes when exactly 6 Stage 1 and 4 Stage 2 answers exist."""
        complete_rows = [
            {"evaluation_id": i, "question_id": i, "question_source": "Question Bank", "evaluation_status": "Completed"}
            for i in range(1, 7)
        ] + [
            {"evaluation_id": i, "question_id": i + 100, "question_source": "groq_llm", "evaluation_status": "Completed"}
            for i in range(7, 11)
        ]
        with patch("Answer_Checking.manual_answer_input.get_exam_evaluation_rows", return_value=complete_rows):
            # Should not raise
            _verify_completed_exam("exam-uuid", 1, 2)


if __name__ == "__main__":
    unittest.main()

