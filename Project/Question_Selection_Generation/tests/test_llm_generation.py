import unittest
from unittest.mock import patch

from Question_Selection_Generation.llm_question_generator import (
    OllamaUnavailableError,
    generate_stage2_questions,
    validate_generated_questions,
)


def payload(difficulties=None):
    difficulties = difficulties or ["Easy", "Easy", "Hard", "Hard"]
    return {"questions": [
        {
            "skill": "Spring Boot",
            "difficulty": difficulty,
            "question": f"How does Spring Boot support configuration approach {index}?",
            "reference_answer": "Spring Boot provides a structured application configuration model. It resolves values from supported configuration sources. The environment can override defaults using documented precedence. Profiles help separate environment-specific settings. Validation and observability make configuration failures easier to detect.",
            "expected_concepts": ["configuration", "profiles", "property precedence"],
        }
        for index, difficulty in enumerate(difficulties)
    ]}


class LLMGenerationTests(unittest.TestCase):
    def test_structured_payload(self):
        questions = validate_generated_questions(payload(), ["Spring Boot"], {"Hard": 2, "Easy": 2}, [])
        self.assertEqual(len(questions), 4)

    def test_core_skill_is_rejected(self):
        bad = payload()
        bad["questions"][0]["skill"] = "OOP"
        with self.assertRaises(ValueError):
            validate_generated_questions(bad, ["Spring Boot"], {"Hard": 2, "Easy": 2}, [])

    @patch("Question_Selection_Generation.llm_question_generator.call_ollama")
    @patch("Question_Selection_Generation.llm_question_generator.check_ollama", return_value=False)
    def test_generation_fails_fast_when_ollama_is_unavailable(self, check_ollama, call_ollama):
        with self.assertRaisesRegex(OllamaUnavailableError, "ollama serve"):
            generate_stage2_questions({}, ["Spring Boot"], 90, [])
        call_ollama.assert_not_called()

    @patch("Question_Selection_Generation.llm_question_generator.call_ollama")
    @patch("Question_Selection_Generation.llm_question_generator.check_ollama", return_value=True)
    def test_connection_failure_is_not_retried(self, check_ollama, call_ollama):
        call_ollama.side_effect = OllamaUnavailableError("server stopped")
        with self.assertRaises(OllamaUnavailableError):
            generate_stage2_questions({}, ["Spring Boot"], 90, [], {"Spring Boot": 90})
        call_ollama.assert_called_once()


if __name__ == "__main__":
    unittest.main()
