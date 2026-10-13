from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from Answer_Checking.manual_answer_input import collect_multiline_answer, main


class TestManualAnswerInput(unittest.TestCase):
    def test_collect_multiline_answer_stops_on_done(self):
        with patch("builtins.input", side_effect=["First line", "Second line", "done"]):
            text = collect_multiline_answer()
        self.assertEqual(text, "First line\nSecond line")

    @patch("Answer_Checking.manual_answer_input.get_stage1_questions")
    @patch("Answer_Checking.manual_answer_input.save_candidate_answer", return_value=42)
    @patch(
        "builtins.input",
        side_effect=[
            "1",
            "7",
            "Answer 1",
            "done",
            "Answer 2",
            "done",
            "Answer 3",
            "done",
            "Answer 4",
            "done",
            "Answer 5",
            "done",
            "Answer 6",
            "done",
            "finish",
        ],
    )
    def test_main_saves_all_questions_in_order(self, _mock_input, mock_save, mock_questions):
        mock_questions.return_value = [
            {"question_id": question_id, "question": f"Question text {question_id}"}
            for question_id in range(1, 7)
        ]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            main()
        output = buffer.getvalue()
        self.assertEqual(_mock_input.call_args_list[0].args[0], "Enter JD ID: ")
        self.assertEqual(_mock_input.call_args_list[1].args[0], "Enter Candidate ID: ")
        self.assertIn("Question 1: Question text 1", output)
        self.assertIn("Question 6: Question text 6", output)
        self.assertIn("All six answers were saved successfully.", output)
        mock_questions.assert_called_once_with(1)
        self.assertEqual(
            mock_save.call_args_list,
            [
                unittest.mock.call(1, question_id, f"Answer {question_id}", 7)
                for question_id in range(1, 7)
            ],
        )


if __name__ == "__main__":
    unittest.main()
