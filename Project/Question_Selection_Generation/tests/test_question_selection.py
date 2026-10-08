import random
import unittest

from Question_Selection_Generation.question_selector import determine_stage2_difficulty, validate_stage1_questions, SelectedQuestion


class QuestionSelectionTests(unittest.TestCase):
    def test_stage1_distribution_validation(self):
        questions = [
            SelectedQuestion(i, "subject", "topic", f"question {i}", "answer", "concept", difficulty)
            for i, difficulty in enumerate(["Easy", "Easy", "Easy", "Medium", "Medium", "Hard"], 1)
        ]
        self.assertEqual(validate_stage1_questions(questions), [])

    def test_stage2_boundaries(self):
        self.assertEqual(determine_stage2_difficulty(100), {"Hard": 4})
        self.assertEqual(determine_stage2_difficulty(81), {"Hard": 4})
        self.assertEqual(determine_stage2_difficulty(80), {"Hard": 2, "Easy": 2})
        self.assertEqual(determine_stage2_difficulty(60), {"Hard": 2, "Easy": 2})
        self.assertEqual(determine_stage2_difficulty(59), {"Easy": 4})

    def test_invalid_score_rejected(self):
        with self.assertRaises(ValueError):
            determine_stage2_difficulty(101)


if __name__ == "__main__":
    unittest.main()
