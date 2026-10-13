from __future__ import annotations

import io
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from Answer_Checking.manual_answer_input import collect_multiline_answer, _collect_stage1


class TestManualAnswerInput(unittest.TestCase):
    def test_collect_multiline_answer_stops_on_done(self):
        with patch("builtins.input", side_effect=["First line", "Second line", "done"]):
            text = collect_multiline_answer()
        self.assertEqual(text, "First line\nSecond line")

    @patch("Answer_Checking.manual_answer_input.save_candidate_answer", return_value=42)
    @patch(
        "builtins.input",
        side_effect=[
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
    def test_stage1_collection_saves_all_questions_in_order(self, _mock_input, mock_save):
        questions = [
            {"question_id": question_id, "question": f"Question text {question_id}"}
            for question_id in range(1, 7)
        ]
        buffer = io.StringIO()
        with redirect_stdout(buffer):
            _collect_stage1(1, 7, "exam-1", questions)
        output = buffer.getvalue()
        self.assertIn("Question 1: Question text 1", output)
        self.assertIn("Question 6: Question text 6", output)
        self.assertEqual(
            mock_save.call_args_list,
            [
                unittest.mock.call(1, question_id, f"Answer {question_id}", 7, "exam-1")
                for question_id in range(1, 7)
            ],
        )


if __name__ == "__main__":
    unittest.main()
