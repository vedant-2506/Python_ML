from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from Answer_Checking.run_evaluation import main


class TestRunEvaluation(unittest.TestCase):
    @patch("sys.argv", ["run_evaluation"])
    @patch("Answer_Checking.run_evaluation.calculate_and_store_final_result")
    @patch("Answer_Checking.run_evaluation.get_first_six_average", return_value=Decimal("80"))
    @patch("Answer_Checking.run_evaluation.update_evaluation_result")
    @patch("Answer_Checking.run_evaluation.evaluate_pending_record")
    @patch("Answer_Checking.run_evaluation.get_pending_answers")
    def test_repairs_unscored_review_row_and_persists_exam_result(
        self,
        get_pending,
        evaluate,
        update,
        get_average,
        store_final,
    ):
        record = {
            "evaluation_id": 23,
            "evaluation_status": "Review Required",
            "answer_score": None,
            "factual_correctness_score": None,
            "exam_id": "exam-1",
            "candidate_id": 7,
            "jd_id": 2,
        }
        get_pending.return_value = [record]
        evaluate.return_value = {
            "evaluation_status": "Review Required",
            "answer_score": 72.0,
            "factual_correctness_score": 80.0,
        }

        main()

        update.assert_called_once_with(23, evaluate.return_value)
        get_average.assert_called_once_with(7, 2, exam_id="exam-1")
        store_final.assert_called_once_with("exam-1", 7, 2)


if __name__ == "__main__":
    unittest.main()
