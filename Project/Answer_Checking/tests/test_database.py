from __future__ import annotations

import unittest
from decimal import Decimal
from uuid import UUID
from unittest.mock import patch

from Answer_Checking.database import (
    calculate_first_six_average,
    get_first_six_average,
    save_candidate_answer,
)


class FakeCursor:
    def __init__(self):
        self._results = [None, (7,)]
        self._call_count = 0
        self.executed = []
        self.rowcount = 1
        self.fetchall_result = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        return False

    def execute(self, *args, **kwargs):
        self.executed.append(args)

    def fetchone(self):
        result = self._results[self._call_count]
        self._call_count += 1
        return result

    def fetchall(self):
        return self.fetchall_result


class FakeConnection:
    def __init__(self):
        self.cursor_obj = FakeCursor()

    def cursor(self):
        return self.cursor_obj

    def commit(self):
        return None

    def rollback(self):
        return None

    def close(self):
        return None


class TestDatabase(unittest.TestCase):
    @patch("Answer_Checking.database.get_question_details")
    @patch("Answer_Checking.database.get_database_connection")
    def test_save_candidate_answer_inserts_record(
        self,
        mock_connect,
        mock_question_details,
    ):
        mock_question_details.return_value = {
            "expected_answer": "Overfitting is memorization.",
            "difficulty": "Medium",
            "expected_concepts": ["memorization", "generalization"],
        }
        mock_connect.return_value = FakeConnection()

        evaluation_id = save_candidate_answer(
            1,
            5,
            "Overfitting is memorization.",
            "bb0e8400-e29b-41d4-a716-446655440000",
        )

        self.assertEqual(evaluation_id, 7)
        duplicate_query = mock_connect.return_value.cursor_obj.executed[1]
        self.assertIn("WHERE attempt_id = %s", duplicate_query[0])
        self.assertEqual(
            duplicate_query[1][0],
            "bb0e8400-e29b-41d4-a716-446655440000",
        )
        insert_parameters = mock_connect.return_value.cursor_obj.executed[-1][1]
        self.assertEqual(insert_parameters[0], "bb0e8400-e29b-41d4-a716-446655440000")
        self.assertEqual(insert_parameters[6], 12.0)

    @patch("Answer_Checking.database.get_question_details", side_effect=ValueError("not found"))
    def test_save_candidate_answer_rejects_missing_question(self, _mock_details):
        with self.assertRaises(ValueError):
            save_candidate_answer(
                999,
                999,
                "candidate answer",
                "bb0e8400-e29b-41d4-a716-446655440000",
            )

    @patch("Answer_Checking.database.get_database_connection")
    def test_result_update_refuses_non_pending_record(self, mock_connect):
        connection = FakeConnection()
        connection.cursor_obj.rowcount = 0
        mock_connect.return_value = connection

        with self.assertRaisesRegex(ValueError, "no longer pending"):
            from Answer_Checking.database import update_evaluation_result

            update_evaluation_result(7, {"evaluation_status": "Completed"})

        sql = connection.cursor_obj.executed[-1][0]
        self.assertIn("AND evaluation_status = 'Pending'", sql)

    @patch("Answer_Checking.database.get_database_connection")
    def test_result_update_persists_result_without_average_column(self, mock_connect):
        connection = FakeConnection()
        mock_connect.return_value = connection

        from Answer_Checking.database import update_evaluation_result

        update_evaluation_result(
            7,
            {
                "semantic_score": 80,
                "factual_correctness_score": 80,
                "answer_score": 80,
                "classification": "Correct",
                "obtained_marks": 9.6,
                "max_marks": 12,
                "evaluation_status": "Completed",
                "evaluation_notes": "Completed",
            },
        )

        update_sql = connection.cursor_obj.executed[-1][0]
        self.assertNotIn("first_six_average", update_sql)
        self.assertIn("AND evaluation_status = 'Pending'", update_sql)

    def test_first_six_average_for_six_completed_distinct_questions(self):
        evaluations = [
            (evaluation_id, question_id, score, "Completed", "answer")
            for evaluation_id, (question_id, score) in enumerate(
                [(1, 80), (2, 70), (3, 90), (4, 60), (5, 100), (6, 50)],
                start=1,
            )
        ]

        self.assertEqual(calculate_first_six_average(evaluations), 75)

    def test_first_six_average_is_not_set_for_fewer_than_six_questions(self):
        evaluations = [
            (evaluation_id, question_id, 80, "Completed", "answer")
            for evaluation_id, question_id in enumerate(range(1, 6), start=1)
        ]

        self.assertIsNone(calculate_first_six_average(evaluations))

    def test_duplicate_question_uses_latest_evaluation_without_double_counting(self):
        evaluations = [
            (1, 1, 20, "Completed", "older answer"),
            (2, 1, 80, "Completed", "latest answer"),
            (3, 2, 80, "Completed", "answer"),
            (4, 3, 80, "Completed", "answer"),
            (5, 4, 80, "Completed", "answer"),
            (6, 5, 80, "Completed", "answer"),
            (7, 6, 80, "Completed", "answer"),
        ]

        self.assertEqual(calculate_first_six_average(evaluations), 80)

    @patch("Answer_Checking.database.get_database_connection")
    def test_different_attempts_are_not_combined(self, mock_connect):
        attempt_ids = [
            UUID("bb0e8400-e29b-41d4-a716-446655440000"),
            UUID("bb0e8400-e29b-41d4-a716-446655440001"),
        ]
        attempt_questions = [
            (evaluation_id, question_id, 80, "Completed", "answer")
            for evaluation_id, question_id in enumerate(range(1, 4), start=1)
        ]

        for attempt_id in attempt_ids:
            connection = FakeConnection()
            connection.cursor_obj.fetchall_result = attempt_questions
            mock_connect.return_value = connection

            self.assertIsNone(get_first_six_average(attempt_id, 1))
            question_query = connection.cursor_obj.executed[0]
            self.assertIn("WHERE ae.attempt_id = %s", question_query[0])
            self.assertEqual(question_query[1], (str(attempt_id), 1))

    @patch("Answer_Checking.database.get_database_connection")
    def test_average_for_complete_attempt_is_calculated_on_demand(self, mock_connect):
        connection = FakeConnection()
        connection.cursor_obj.fetchall_result = [
            (question_id, question_id, 80, "Completed", "answer")
            for question_id in range(1, 7)
        ]
        mock_connect.return_value = connection

        average = get_first_six_average(
            "bb0e8400-e29b-41d4-a716-446655440000",
            1,
        )

        self.assertEqual(average, 80)
        self.assertIn("qe.stage = 1", connection.cursor_obj.executed[0][0])
        self.assertEqual(len(connection.cursor_obj.executed), 1)

    def test_review_required_scores_produce_provisional_first_six_average(self):
        evaluations = [
            (
                evaluation_id,
                question_id,
                80,
                "Review Required" if question_id == 3 else "Completed",
                "answer",
            )
            for evaluation_id, question_id in enumerate(range(1, 7), start=1)
        ]

        self.assertEqual(calculate_first_six_average(evaluations), 80)

    def test_failed_evaluation_prevents_first_six_average(self):
        evaluations = [
            (
                question_id,
                question_id,
                80,
                "Failed" if question_id == 3 else "Completed",
                "answer",
            )
            for question_id in range(1, 7)
        ]

        self.assertIsNone(calculate_first_six_average(evaluations))

    def test_pending_reevaluation_prevents_stale_average(self):
        evaluations = [
            (1, 1, 80, "Completed", "answer"),
            (2, 1, None, "Pending", "reevaluation"),
            *[
                (question_id + 1, question_id, 80, "Completed", "answer")
                for question_id in range(2, 7)
            ],
        ]

        self.assertIsNone(calculate_first_six_average(evaluations))

    def test_missing_candidate_answer_does_not_count_as_evaluated_zero(self):
        evaluations = [
            (
                question_id,
                question_id,
                0 if question_id == 1 else 80,
                "Completed",
                None if question_id == 1 else "answer",
            )
            for question_id in range(1, 7)
        ]

        self.assertIsNone(calculate_first_six_average(evaluations))

    def test_explicit_empty_answer_counts_its_completed_zero_score(self):
        evaluations = [
            (
                question_id,
                question_id,
                0 if question_id == 1 else 100,
                "Completed",
                "" if question_id == 1 else "answer",
            )
            for question_id in range(1, 7)
        ]

        self.assertEqual(calculate_first_six_average(evaluations), Decimal("83.33"))


if __name__ == "__main__":
    unittest.main()
