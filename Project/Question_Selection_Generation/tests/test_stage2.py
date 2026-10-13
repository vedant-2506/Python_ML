from __future__ import annotations

import unittest
from decimal import Decimal
from unittest.mock import patch

from Question_Selection_Generation.adaptive_policy import (
    calculate_percentage,
    determine_stage2_difficulty,
)
from Question_Selection_Generation.llm_question_generator import validate_generated_questions


def evaluations(marks: list[int], status: str = "Completed") -> list[dict]:
    difficulties = ["Easy", "Easy", "Easy", "Medium", "Medium", "Hard"]
    maximums = [6, 6, 6, 12, 12, 18]
    return [
        {
            "evaluation_id": index,
            "question_order": index,
            "difficulty": difficulty,
            "obtained_marks": mark,
            "max_marks": maximum,
            "evaluation_status": status,
        }
        for index, (difficulty, mark, maximum) in enumerate(zip(difficulties, marks, maximums), 1)
    ]


class Stage2PolicyTests(unittest.TestCase):
    def test_percentage_is_calculated_out_of_sixty(self):
        self.assertEqual(calculate_percentage(evaluations([3, 3, 3, 6, 6, 9])), Decimal("50.00"))

    def test_requires_completed_six_valid_evaluations(self):
        with self.assertRaises(ValueError):
            calculate_percentage(evaluations([6, 6, 6, 12, 12, 18], "Review Required"))
        with self.assertRaises(ValueError):
            calculate_percentage(evaluations([6, 6, 6, 12, 12]))

    def test_boundary_and_rounding_policy(self):
        expected = {
            Decimal("0"): {"Easy": 3, "Medium": 1, "Hard": 0},
            Decimal("59"): {"Easy": 3, "Medium": 1, "Hard": 0},
            Decimal("59.49"): {"Easy": 3, "Medium": 1, "Hard": 0},
            Decimal("59.50"): {"Easy": 2, "Medium": 2, "Hard": 0},
            Decimal("60"): {"Easy": 2, "Medium": 2, "Hard": 0},
            Decimal("80"): {"Easy": 2, "Medium": 2, "Hard": 0},
            Decimal("80.50"): {"Easy": 0, "Medium": 3, "Hard": 1},
            Decimal("81"): {"Easy": 0, "Medium": 3, "Hard": 1},
            Decimal("100"): {"Easy": 0, "Medium": 3, "Hard": 1},
        }
        for score, distribution in expected.items():
            self.assertEqual(determine_stage2_difficulty(score), distribution)


class Stage2ValidationTests(unittest.TestCase):
    def payload(self, difficulties=None):
        difficulties = difficulties or ["Easy", "Easy", "Easy", "Medium"]
        return {
            "questions": [
                {
                    "skill": "Spring Boot",
                    "difficulty": difficulty,
                    "question": [
                        "How does Spring Boot resolve configuration properties from multiple sources?",
                        "How should Spring Boot profiles separate deployment environments safely?",
                        "How can Spring Boot validate configuration values during application startup?",
                        "How do Spring Boot configuration properties improve typed application settings?",
                    ][index - 1],
                    "answer": (
                        "Spring Boot loads configuration from several documented sources. "
                        "Profiles select environment-specific values. "
                        "Property precedence determines which value wins. "
                        "Validation can reject invalid configuration early. "
                        "Externalized settings keep deployment configuration separate."
                    ),
                    "expected_concepts": ["profiles", "precedence", "externalized configuration"],
                }
                for index, difficulty in enumerate(difficulties, 1)
            ]
        }

    def test_valid_json_and_exact_distribution(self):
        questions = validate_generated_questions(self.payload(), ["Spring Boot"], {"Easy": 3, "Medium": 1, "Hard": 0}, [])
        self.assertEqual(len(questions), 4)

    def test_rejects_invalid_fields_sentences_skills_and_duplicates(self):
        bad = self.payload()
        bad["questions"][0]["skill"] = "OOP"
        with self.assertRaises(ValueError):
            validate_generated_questions(bad, ["Spring Boot"], {"Easy": 3, "Medium": 1, "Hard": 0}, [])
        bad = self.payload()
        bad["questions"][0]["answer"] = "Only one sentence."
        with self.assertRaises(ValueError):
            validate_generated_questions(bad, ["Spring Boot"], {"Easy": 3, "Medium": 1, "Hard": 0}, [])
        bad = self.payload()
        bad["questions"][1]["question"] = bad["questions"][0]["question"].upper()
        with self.assertRaises(ValueError):
            validate_generated_questions(bad, ["Spring Boot"], {"Easy": 3, "Medium": 1, "Hard": 0}, [])

    @patch("Question_Selection_Generation.llm_question_generator.generate_json")
    @patch("Question_Selection_Generation.llm_question_generator.verify_model")
    def test_generation_retries_invalid_response(self, verify, generate):
        from Question_Selection_Generation.llm_question_generator import generate_stage2_questions

        invalid = self.payload(["Easy", "Easy", "Easy", "Easy"])
        valid = self.payload()
        generate.side_effect = [invalid, valid]
        result = generate_stage2_questions({}, ["Spring Boot"], 45, [])
        self.assertEqual(len(result), 4)
        self.assertEqual(generate.call_count, 2)


if __name__ == "__main__":
    unittest.main()
