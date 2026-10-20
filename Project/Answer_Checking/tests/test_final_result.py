from __future__ import annotations

import unittest
from unittest.mock import patch

from Answer_Checking.final_result import calculate_and_store_final_result, main


class FakeCursor:
    def __init__(self):
        self.executed = []
        self.score_results = [(80,)] * 6 + [(60,)] * 4

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, query, params=None):
        self.executed.append((query, params))

    def fetchone(self):
        return self.score_results.pop(0)


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()
        self.committed = False

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        self.committed = True

    def close(self):
        pass


class TestFinalResult(unittest.TestCase):
    @patch("Answer_Checking.final_result.get_exam_evaluation_rows")
    @patch("Answer_Checking.final_result.get_database_connection")
    def test_creates_result_table_before_upsert(self, mock_connect, mock_rows):
        connection = FakeConnection()
        mock_connect.return_value = connection
        mock_rows.return_value = [
            {
                "evaluation_id": index,
                "evaluation_status": "Completed",
                "question_source": "Question Bank" if index <= 6 else "groq_llm",
            }
            for index in range(1, 11)
        ]

        calculate_and_store_final_result("00000000-0000-0000-0000-000000000001", 7, 2)

        executed = connection.cursor_obj.executed
        self.assertIn(
            "CREATE TABLE IF NOT EXISTS public.final_evaluation_result",
            executed[0][0],
        )
        self.assertIn("INSERT INTO public.final_evaluation_result", executed[-1][0])
        self.assertTrue(connection.committed)

    @patch("builtins.input", side_effect=[
        "00000000-0000-0000-0000-000000000001",
        "7",
        "2",
    ])
    @patch("Answer_Checking.final_result.calculate_and_store_final_result")
    def test_cli_prompts_for_missing_identifiers(
        self,
        mock_calculate,
        _mock_input,
    ):
        main([])

        mock_calculate.assert_called_once_with(
            "00000000-0000-0000-0000-000000000001",
            7,
            2,
        )


if __name__ == "__main__":
    unittest.main()
