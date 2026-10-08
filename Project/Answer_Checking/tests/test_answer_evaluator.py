import unittest

from Answer_Checking.answer_evaluator import AnswerEvaluator, QuestionContext


class AnswerEvaluatorTests(unittest.TestCase):
    def setUp(self):
        self.context = QuestionContext(
            "What is encapsulation?",
            "Encapsulation bundles data and methods in a class and controls access with modifiers.",
            ["data", "methods", "class", "access modifiers"],
        )
        self.evaluator = AnswerEvaluator()

    def test_ordering_and_bounds(self):
        excellent = self.evaluator.evaluate(self.context, "Encapsulation bundles data and methods in a class and protects state with access modifiers.")
        partial = self.evaluator.evaluate(self.context, "It uses a class.")
        irrelevant = self.evaluator.evaluate(self.context, "A network protocol routes packets between computers.")
        empty = self.evaluator.evaluate(self.context, "")
        self.assertGreater(excellent.final_score, partial.final_score)
        self.assertGreater(partial.final_score, irrelevant.final_score)
        self.assertGreater(irrelevant.final_score, empty.final_score)
        for result in (excellent, partial, irrelevant, empty):
            self.assertTrue(0 <= result.final_score <= 100)

    def test_stage_and_final_averages(self):
        scores = [80, 70, 90, 60, 85, 75]
        self.assertEqual(self.evaluator.average(scores), 76.67)
        self.assertEqual(self.evaluator.average(scores + [90, 80, 70, 60]), 76.0)

    def test_missing_reference_is_explicit(self):
        with self.assertRaises(ValueError):
            self.evaluator.evaluate(QuestionContext("q", "", []), "answer")
