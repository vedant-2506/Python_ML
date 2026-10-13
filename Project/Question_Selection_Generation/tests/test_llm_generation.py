"""Compatibility coverage for the public Stage 2 validation API."""
from __future__ import annotations

import unittest

from Question_Selection_Generation.llm_question_generator import validate_generated_questions


class LLMGenerationTests(unittest.TestCase):
    def test_validator_accepts_answer_alias_and_normalizes_output(self):
        payload = {
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
                        "Spring Boot loads configuration from supported sources. "
                        "Profiles select environment-specific settings. "
                        "Property precedence determines the effective value. "
                        "Validation detects invalid values early. "
                        "Externalized settings keep deployments portable."
                    ),
                    "expected_concepts": ["profiles", "precedence", "externalization"],
                }
                for index, difficulty in enumerate(["Easy", "Easy", "Easy", "Medium"], 1)
            ]
        }
        result = validate_generated_questions(payload, ["Spring Boot"], {"Easy": 3, "Medium": 1}, [])
        self.assertEqual(len(result), 4)
        self.assertEqual(result[0].reference_answer.count("."), 5)

    def test_core_skill_is_rejected(self):
        payload = {
            "questions": [
                {
                    "skill": "OOP",
                    "difficulty": "Easy",
                    "question": "Explain polymorphism.",
                    "answer": "One. Two. Three. Four. Five.",
                    "expected_concepts": ["dispatch"],
                }
            ] * 4
        }
        with self.assertRaises(ValueError):
            validate_generated_questions(payload, ["Spring Boot"], {"Easy": 3, "Medium": 1}, [])


if __name__ == "__main__":
    unittest.main()
