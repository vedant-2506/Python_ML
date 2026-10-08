import unittest

from Answer_Checking.answer_preprocessor import preprocess


class PreprocessingTests(unittest.TestCase):
    def test_technical_terms_are_not_corrupted(self):
        expected = {"c++", "c#", ".net", "node.js", "ci/cd", "tcp/ip", "spring boot", "sql"}
        self.assertTrue(expected.issubset(set(preprocess("C++ C# .NET Node.js CI/CD TCP/IP Spring Boot SQL").tokens)))

    def test_empty_and_whitespace_are_safe(self):
        self.assertEqual(preprocess(None).tokens, ())
        self.assertEqual(preprocess("   ").tokens, ())
