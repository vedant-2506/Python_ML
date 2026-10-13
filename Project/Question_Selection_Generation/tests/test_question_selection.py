import unittest

from Question_Selection_Generation.question_selector import (
    SelectedQuestion,
    classify_skills,
    normalize_difficulty,
    normalize_question,
    select_stage1_questions,
    validate_stage1_questions,
)


class QuestionSelectionTests(unittest.TestCase):
    def test_core_and_changeable_policy_includes_language_tokens(self):
        result = classify_skills(["SDLC", "C", "C++", "Java", "SQL", "Git", "Spring Boot", "Docker"])
        self.assertEqual(
            result.core_skills,
            ["Software Development Life Cycle (SDLC)", "C", "C++", "Java", "SQL", "Git / Version Control"],
        )
        self.assertEqual(result.changeable_skills, ["Spring Boot", "Docker"])
        self.assertEqual(result.unclassified_skills, [])

    def test_only_core_and_only_changeable(self):
        self.assertEqual(classify_skills(["OOP", "DBMS", "Python"]).changeable_skills, [])
        self.assertEqual(
            classify_skills(["React", "Kubernetes", "AWS"]).core_skills,
            [],
        )

    def test_aliases_case_whitespace_and_duplicates(self):
        result = classify_skills([" object-oriented   programming ", "OOP", "software development life cycle", "SDLC", "git"])
        self.assertEqual(
            result.core_skills,
            ["Object-Oriented Programming (OOP)", "Software Development Life Cycle (SDLC)", "Git / Version Control"],
        )

    def test_language_tokens_never_collapse(self):
        result = classify_skills(["C", "C++", "C#", "Java", "JavaScript"])
        self.assertEqual(result.core_skills, ["C", "C++", "C#", "Java", "JavaScript"])

    def test_nested_missing_and_unknown_skills_are_retained(self):
        self.assertEqual(classify_skills(None).unclassified_skills, [])
        result = classify_skills([{"name": "SQL"}, {"skill": "Internal Platform"}, []])
        self.assertEqual(result.core_skills, ["SQL"])
        self.assertEqual(result.unclassified_skills, ["Internal Platform"])

    def test_normalization_and_distribution_validation(self):
        questions = [
            SelectedQuestion(i, "subject", "topic", f"question {i}", "answer", "concept", difficulty)
            for i, difficulty in enumerate(["Easy", "Easy", "Easy", "Medium", "Medium", "Hard"], 1)
        ]
        self.assertEqual(validate_stage1_questions(questions), [])
        self.assertEqual(normalize_difficulty(" medium "), "Medium")
        self.assertEqual(normalize_question(" A  Question! "), "a question")

    def test_validation_normalizes_lowercase_difficulty_and_handles_none_text(self):
        questions = [
            SelectedQuestion(i, "subject", "topic", f"question {i}", "answer", "concept", difficulty)
            for i, difficulty in enumerate(["easy", "easy", "easy", "medium", "medium", "hard"], 1)
        ]
        self.assertEqual(validate_stage1_questions(questions), [])
        self.assertEqual(normalize_question(None), "")

    def test_duplicate_text_is_rejected(self):
        questions = [
            SelectedQuestion(i, "subject", "topic", "question 1" if i == 2 else f"question {i}", "answer", "concept", difficulty)
            for i, difficulty in enumerate(["Easy", "Easy", "Easy", "Medium", "Medium", "Hard"], 1)
        ]
        self.assertIn("duplicate question text", validate_stage1_questions(questions))

    def test_stage2_boundaries_and_invalid_score(self):
        from Question_Selection_Generation.question_selector import determine_stage2_difficulty

        self.assertEqual(determine_stage2_difficulty(100), {"Easy": 0, "Medium": 3, "Hard": 1})
        self.assertEqual(determine_stage2_difficulty(80), {"Easy": 2, "Medium": 2, "Hard": 0})
        self.assertEqual(determine_stage2_difficulty(59), {"Easy": 3, "Medium": 1, "Hard": 0})
        with self.assertRaises(ValueError):
            determine_stage2_difficulty(101)

    def test_shortage_fails_without_inserting(self):
        class EmptyCursor:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def execute(self, *args):
                pass

            def fetchall(self):
                return []

        class EmptyConnection:
            def cursor(self):
                return EmptyCursor()

        with self.assertRaisesRegex(ValueError, "cannot satisfy"):
            select_stage1_questions(EmptyConnection(), ["SQL"])


if __name__ == "__main__":
    unittest.main()
