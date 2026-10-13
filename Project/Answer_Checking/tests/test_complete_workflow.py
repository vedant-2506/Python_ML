"""Unit tests for the complete 10-question RankResume workflow."""
from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from decimal import Decimal
from unittest.mock import MagicMock, call, patch

from Question_Selection_Generation.adaptive_policy import (
    DEFAULT_STAGE2_DISTRIBUTION,
    resolve_stage2_difficulty,
)
from Answer_Checking.manual_answer_input import main, _collect_stage1, _collect_stage2, _verify_completed_exam


class TestAdaptivePolicyResolution(unittest.TestCase):
    def test_resolve_default_when_none(self):
        dist, pct, is_adapt = resolve_stage2_difficulty(None)
        self.assertEqual(dist, {"Easy": 2, "Medium": 2, "Hard": 0})
        self.assertIsNone(pct)
        self.assertFalse(is_adapt)

    def test_resolve_default_when_pending_or_review_required(self):
        evals = [
            {"evaluation_id": i, "question_order": i, "difficulty": d, "obtained_marks": 5, "max_marks": m, "evaluation_status": "Review Required"}
            for i, (d, m) in enumerate([("Easy", 6), ("Easy", 6), ("Easy", 6), ("Medium", 12), ("Medium", 12), ("Hard", 18)], 1)
        ]
        dist, pct, is_adapt = resolve_stage2_difficulty(evals)
        self.assertEqual(dist, {"Easy": 2, "Medium": 2, "Hard": 0})
        self.assertIsNone(pct)
        self.assertFalse(is_adapt)

    def test_resolve_adaptive_when_all_completed(self):
        evals = [
            {"evaluation_id": i, "question_order": i, "difficulty": d, "obtained_marks": m, "max_marks": m, "evaluation_status": "Completed"}
            for i, (d, m) in enumerate([("Easy", 6), ("Easy", 6), ("Easy", 6), ("Medium", 12), ("Medium", 12), ("Hard", 18)], 1)
        ]
        dist, pct, is_adapt = resolve_stage2_difficulty(evals)
        self.assertEqual(pct, Decimal("100.00"))
        self.assertEqual(dist, {"Easy": 0, "Medium": 3, "Hard": 1})
        self.assertTrue(is_adapt)


class TestCompleteWorkflow(unittest.TestCase):
    @patch("Answer_Checking.manual_answer_input.get_database_connection")
    @patch("Answer_Checking.manual_answer_input._verify_completed_exam")
    @patch("Answer_Checking.manual_answer_input.save_candidate_answer")
    @patch("Answer_Checking.manual_answer_input.generate_or_reuse_stage2")
    @patch("Answer_Checking.manual_answer_input.get_stage1_questions")
    @patch("Answer_Checking.manual_answer_input.get_candidate_exam_ids", return_value=[])
    @patch("Answer_Checking.manual_answer_input.get_latest_exam_id", return_value="exam-uuid-123")
    @patch("Answer_Checking.manual_answer_input._ensure_exam_schema")
    @patch("Answer_Checking.manual_answer_input.get_exam_evaluation_rows")
    def test_full_ten_question_flow(
        self,
        mock_eval_rows,
        mock_ensure_schema,
        mock_latest_exam,
        mock_candidate_exams,
        mock_stage1_questions,
        mock_stage2,
        mock_save,
        mock_verify,
        mock_db_conn,
    ):
        mock_stage1_questions.return_value = [
            {"question_id": i, "question": f"Stage 1 Q{i}"} for i in range(1, 7)
        ]
        mock_eval_rows.side_effect = [
            [],  # initial check (no answers saved yet)
            [],  # stage 2 check (no stage 2 answers saved yet)
            [{"evaluation_id": i, "question_id": i, "evaluation_status": "Pending"} for i in range(1, 11)],  # verify check
        ]
        mock_stage2.return_value = {
            "reused": False,
            "adaptive": False,
            "distribution": {"Easy": 2, "Medium": 2, "Hard": 0},
            "questions": [
                {
                    "ai_question_exam_id": 100 + i,
                    "question_order": i,
                    "question": f"Generated Q{i+6}",
                    "answer": f"Ref answer {i+6}",
                    "difficulty": "Easy" if i <= 2 else "Medium",
                    "skill": "REST API",
                }
                for i in range(1, 5)
            ],
        }

        # Terminal inputs:
        # JD ID = 2
        # Candidate ID = 3
        # 6 answers (each with "done")
        # "finish"
        # 4 answers (each with "done")
        inputs = [
            "2",
            "3",
            "Answer 1", "done",
            "Answer 2", "done",
            "Answer 3", "done",
            "Answer 4", "done",
            "Answer 5", "done",
            "Answer 6", "done",
            "finish",
            "Answer 7", "done",
            "Answer 8", "done",
            "Answer 9", "done",
            "Answer 10", "done",
        ]

        buffer = io.StringIO()
        with patch("builtins.input", side_effect=inputs):
            with redirect_stdout(buffer):
                main()

        output = buffer.getvalue()
        self.assertIn("RANKRESUME EXAM", output)
        self.assertIn("Question 1: Stage 1 Q1", output)
        self.assertIn("Question 1 saved.", output)
        self.assertIn("Question 6 saved.", output)
        self.assertIn("Stage 1 answers saved successfully.", output)
        self.assertIn("Generating four additional questions using the LLM...", output)
        self.assertIn("Question 7: Generated Q7", output)
        self.assertIn("Question 7 saved.", output)
        self.assertIn("Question 10: Generated Q10", output)
        self.assertIn("Question 10 saved.", output)
        self.assertIn("All ten questions and candidate responses have been saved.", output)

        # Ensure all 10 answers were saved
        self.assertEqual(mock_save.call_count, 10)
        # Ensure Stage 2 answers were saved with ai_question_exam_id
        saved_qids = [call_args[0][1] for call_args in mock_save.call_args_list]
        self.assertEqual(saved_qids, [1, 2, 3, 4, 5, 6, 101, 102, 103, 104])

    @patch("Answer_Checking.manual_answer_input.get_database_connection")
    @patch("Answer_Checking.manual_answer_input._verify_completed_exam")
    @patch("Answer_Checking.manual_answer_input.save_candidate_answer")
    @patch("Answer_Checking.manual_answer_input.generate_or_reuse_stage2")
    @patch("Answer_Checking.manual_answer_input.get_stage1_questions")
    @patch("Answer_Checking.manual_answer_input.get_candidate_exam_ids", return_value=["exam-uuid-123"])
    @patch("Answer_Checking.manual_answer_input._ensure_exam_schema")
    @patch("Answer_Checking.manual_answer_input.get_exam_evaluation_rows")
    def test_resuming_flow_skips_answered_questions(
        self,
        mock_eval_rows,
        mock_ensure_schema,
        mock_candidate_exams,
        mock_stage1_questions,
        mock_stage2,
        mock_save,
        mock_verify,
        mock_db_conn,
    ):
        mock_stage1_questions.return_value = [
            {"question_id": i, "question": f"Stage 1 Q{i}"} for i in range(1, 7)
        ]
        # Candidate already answered questions 1 to 6
        existing_stage1 = [
            {"evaluation_id": i, "question_id": i, "evaluation_status": "Review Required"}
            for i in range(1, 7)
        ]
        mock_eval_rows.side_effect = [
            existing_stage1,  # initial check
            existing_stage1,  # stage 2 check
            existing_stage1 + [{"evaluation_id": 100+i, "question_id": 100+i, "evaluation_status": "Pending"} for i in range(1, 5)],
        ]
        mock_stage2.return_value = {
            "reused": True,
            "adaptive": False,
            "distribution": {"Easy": 2, "Medium": 2, "Hard": 0},
            "questions": [
                {
                    "ai_question_exam_id": 100 + i,
                    "question_order": i,
                    "question": f"Generated Q{i+6}",
                    "answer": f"Ref answer {i+6}",
                    "difficulty": "Easy" if i <= 2 else "Medium",
                    "skill": "REST API",
                }
                for i in range(1, 5)
            ],
        }

        # Terminal inputs:
        # JD ID = 2, Candidate ID = 3
        # finish (since Stage 1 questions are already answered)
        # 4 answers for questions 7-10
        inputs = [
            "2",
            "3",
            "finish",
            "Answer 7", "done",
            "Answer 8", "done",
            "Answer 9", "done",
            "Answer 10", "done",
        ]

        buffer = io.StringIO()
        with patch("builtins.input", side_effect=inputs):
            with redirect_stdout(buffer):
                main()

        output = buffer.getvalue()
        # Stage 1 questions should NOT be asked again!
        self.assertNotIn("Question 1: Stage 1 Q1", output)
        self.assertIn("Stage 1 answers saved successfully.", output)
        self.assertIn("Question 7: Generated Q7", output)
        self.assertIn("Question 7 saved.", output)
        self.assertIn("Question 10 saved.", output)
        self.assertIn("All ten questions and candidate responses have been saved.", output)

        # Only 4 answers (questions 7-10) should be saved!
        self.assertEqual(mock_save.call_count, 4)


if __name__ == "__main__":
    unittest.main()
