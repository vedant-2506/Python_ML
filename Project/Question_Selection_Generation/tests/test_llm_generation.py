import unittest

from Question_Selection_Generation.llm_question_generator import validate_generated_questions


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


if __name__ == "__main__":
    unittest.main()
