from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from Answer_Checking.manual_answer_input import collect_multiline_answer, main


class TestManualAnswerInput(unittest.TestCase):
    def test_collect_multiline_answer_stops_on_end_answer(self):
        with patch("builtins.input", side_effect=["First line", "Second line", "END_ANSWER"]):
            text = collect_multiline_answer()
        self.assertEqual(text, "First line\nSecond line")

    @patch("Answer_Checking.manual_answer_input.save_candidate_answer", return_value=42)
    @patch(
        "builtins.input",
        side_effect=[
            "1",
            "5",
            "bb0e8400-e29b-41d4-a716-446655440000",
            "Alpha",
            "END_ANSWER",
        ],
    )
    def test_main_saves_candidate_answer(self, _mock_input, mock_save):
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main()
        self.assertIn("Evaluation ID: 42", buffer.getvalue())
        mock_save.assert_called_once_with(
            1,
            5,
            "Alpha",
            "bb0e8400-e29b-41d4-a716-446655440000",
        )


if __name__ == "__main__":
    unittest.main()
