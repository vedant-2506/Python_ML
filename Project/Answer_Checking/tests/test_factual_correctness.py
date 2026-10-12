from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

import numpy as np

from Answer_Checking.factual_correctness import calculate_factual_correctness, run_nli_prediction


class DummyNLI:
    def __init__(self, logits):
        self.logits = logits
        self.model = SimpleNamespace(
            config=SimpleNamespace(
                id2label={
                    0: "contradiction",
                    1: "entailment",
                    2: "neutral",
                }
            )
        )

    def predict(self, pairs):
        self.pairs = pairs
        return np.asarray([self.logits], dtype=float)


class TestFactualCorrectness(unittest.TestCase):
    def test_factual_correctness_computes_with_expected_facts(self):
        model = DummyNLI([0.0, 5.0, 0.0])
        with mock.patch(
            "Answer_Checking.factual_correctness.load_nli_model",
            return_value=model,
        ) as load_model:
            result = calculate_factual_correctness(
                "Overfitting occurs when a model memorizes training data.",
                ["Overfitting occurs when a model memorizes training data."],
            )

        load_model.assert_called_once_with()
        self.assertEqual(result["status"], "Completed")
        self.assertEqual(result["score"], 100.0)

    def test_prediction_uses_model_label_mapping_for_numpy_logits(self):
        scores = run_nli_prediction("a fact", "a claim", model=DummyNLI([0.0, 5.0, 0.0]))

        self.assertGreater(scores["entailment"], 0.98)
        self.assertLess(scores["contradiction"], 0.01)
        self.assertLess(scores["neutral"], 0.01)

    def test_missing_expected_facts_marks_review(self):
        result = calculate_factual_correctness("The model never learns.", [])
        self.assertEqual(result["status"], "Review Required")
        self.assertIsNone(result["score"])

    def test_unverified_claim_gets_conservative_numeric_score(self):
        result = calculate_factual_correctness(
            "It works very well.",
            ["Overfitting occurs when a model memorizes training data."],
            model=DummyNLI([0.0, 0.0, 0.0]),
        )
        self.assertEqual(result["status"], "Review Required")
        self.assertEqual(result["claims"][0]["status"], "Unverified")
        self.assertIsNotNone(result["score"])
        self.assertGreaterEqual(result["score"], 0.0)
        self.assertLessEqual(result["score"], 100.0)
        self.assertIn("entailment-margin", result["notes"])

    def test_model_loading_error_is_logged_and_raised(self):
        with (
            mock.patch(
                "Answer_Checking.factual_correctness._load_nli_model",
                side_effect=OSError("NLI weights unavailable"),
            ),
            self.assertLogs("Answer_Checking.factual_correctness", level="ERROR") as logs,
        ):
            with self.assertRaisesRegex(OSError, "NLI weights unavailable"):
                calculate_factual_correctness("A claim.", ["A verified fact."])

        self.assertIn("NLI weights unavailable", "\n".join(logs.output))


if __name__ == "__main__":
    unittest.main()
