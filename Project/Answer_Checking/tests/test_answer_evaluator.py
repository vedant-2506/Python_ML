from __future__ import annotations

import unittest
from unittest import mock

from Answer_Checking.answer_evaluator import classify_answer, evaluate_pending_record


class TestAnswerEvaluator(unittest.TestCase):
    def test_classify_answer_thresholds(self):
        self.assertEqual(classify_answer(75), "Correct")
        self.assertEqual(classify_answer(60), "Partially Correct")
        self.assertEqual(classify_answer(20), "Incorrect")

    def test_empty_answer_is_zero_and_incorrect(self):
        result = evaluate_pending_record({
            "candidate_answer": "   ",
            "expected_answer": "Overfitting is memorization.",
            "expected_facts": ["Overfitting is memorization."],
            "max_marks": 10,
        })
        self.assertEqual(result["classification"], "Incorrect")
        self.assertEqual(result["answer_score"], 0.0)
        self.assertEqual(result["obtained_marks"], 0.0)

    def test_missing_max_marks_uses_default(self):
        with (
            mock.patch(
                "Answer_Checking.answer_evaluator.calculate_semantic_score",
                return_value=(80.0, {"note": "semantic test"}),
            ),
            mock.patch(
                "Answer_Checking.answer_evaluator.calculate_factual_correctness",
                return_value={"score": 100.0, "status": "Completed", "notes": "NLI test"},
            ),
        ):
            result = evaluate_pending_record({
                "candidate_answer": "Overfitting occurs when a model memorizes training data.",
                "expected_answer": "Overfitting occurs when a model memorizes training data.",
                "expected_facts": "overfitting, Python, definition, correctness, trade-offs",
                "max_marks": None,
            })
        self.assertEqual(result["evaluation_status"], "Completed")
        self.assertIsNotNone(result["factual_correctness_score"])
        self.assertIsNotNone(result["answer_score"])
        self.assertIsNotNone(result["obtained_marks"])
        self.assertEqual(result["answer_score"], 90.0)
        self.assertAlmostEqual(result["obtained_marks"], 9.0)

    def test_marks_are_assigned_by_difficulty(self):
        expected_marks = {"Easy": 6.0, "Medium": 12.0, "Hard": 18.0}

        for difficulty, max_marks in expected_marks.items():
            with (
                self.subTest(difficulty=difficulty),
                mock.patch(
                    "Answer_Checking.answer_evaluator.calculate_semantic_score",
                    return_value=(80.0, {"note": "semantic test"}),
                ),
                mock.patch(
                    "Answer_Checking.answer_evaluator.calculate_factual_correctness",
                    return_value={"score": 100.0, "status": "Completed", "notes": "NLI test"},
                ),
            ):
                result = evaluate_pending_record({
                    "candidate_answer": "Candidate answer.",
                    "expected_answer": "Reference answer.",
                    "expected_facts": ["Verified fact."],
                    "difficulty": difficulty,
                    "max_marks": 10.0,
                })

            self.assertEqual(result["max_marks"], max_marks)
            self.assertEqual(result["answer_score"], 90.0)
            self.assertAlmostEqual(result["obtained_marks"], max_marks * 0.9)

    def test_missing_expected_facts_uses_reference_answer(self):
        with (
            mock.patch(
                "Answer_Checking.answer_evaluator.calculate_semantic_score",
                return_value=(80.0, {"note": "semantic test"}),
            ),
            mock.patch(
                "Answer_Checking.answer_evaluator.calculate_factual_correctness",
                return_value={"score": 100.0, "status": "Completed", "notes": "NLI test"},
            ),
        ):
            result = evaluate_pending_record({
                "candidate_answer": "Overfitting occurs when a model memorizes training data.",
                "expected_answer": "Overfitting occurs when a model memorizes training data.",
                "expected_facts": None,
                "max_marks": 10,
            })
        self.assertIsNotNone(result["factual_correctness_score"])
        self.assertIsNotNone(result["answer_score"])
        self.assertIn("reference answer was used", result["evaluation_notes"])

    def test_unverified_answer_persists_numeric_scores_for_review(self):
        with (
            mock.patch(
                "Answer_Checking.answer_evaluator.calculate_semantic_score",
                return_value=(80.0, {"note": "semantic test"}),
            ),
            mock.patch(
                "Answer_Checking.answer_evaluator.calculate_factual_correctness",
                return_value={
                    "score": 50.0,
                    "status": "Review Required",
                    "notes": "Unverified claims received conservative entailment-margin scores.",
                },
            ),
        ):
            result = evaluate_pending_record({
                "candidate_answer": "It works very well.",
                "expected_answer": "Overfitting occurs when a model memorizes training data.",
                "expected_facts": ["overfitting"],
                "max_marks": None,
            })
        self.assertEqual(result["evaluation_status"], "Review Required")
        self.assertEqual(result["answer_score"], 65.0)
        self.assertIsNotNone(result["factual_correctness_score"])
        self.assertIsNotNone(result["answer_score"])
        self.assertIsNotNone(result["obtained_marks"])


if __name__ == "__main__":
    unittest.main()
