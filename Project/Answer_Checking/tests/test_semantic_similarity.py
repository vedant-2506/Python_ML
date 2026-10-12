from __future__ import annotations

import unittest
from unittest import mock

import numpy as np

from Answer_Checking.semantic_similarity import calculate_semantic_score


class DummyEncoder:
    def encode(self, text):
        if "overfitting" in text.lower():
            return np.array([1.0, 0.0], dtype=float)
        return np.array([0.0, 1.0], dtype=float)


class TestSemanticSimilarity(unittest.TestCase):
    def test_semantic_score_is_non_negative(self):
        score, details = calculate_semantic_score("Overfitting is memorization.", "Overfitting is memorization.", model=DummyEncoder())
        self.assertGreaterEqual(score, 0.0)
        self.assertLessEqual(score, 100.0)
        self.assertEqual(details["status"], "computed")

    def test_empty_answer_returns_zero(self):
        score, details = calculate_semantic_score("", "   ")
        self.assertEqual(score, 0.0)
        self.assertEqual(details["status"], "empty")

    def test_model_loading_error_is_logged_and_raised(self):
        with (
            mock.patch(
                "Answer_Checking.semantic_similarity._load_semantic_model",
                side_effect=OSError("model weights unavailable"),
            ),
            self.assertLogs("Answer_Checking.semantic_similarity", level="ERROR") as logs,
        ):
            with self.assertRaisesRegex(OSError, "model weights unavailable"):
                calculate_semantic_score("expected answer", "candidate answer")

        self.assertIn("model weights unavailable", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
