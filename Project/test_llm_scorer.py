import inspect
import os
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from google.genai import errors

import ATS_calculation.LLM_based.llm_scorer as llm_scorer
from ATS_calculation import ats_calculator
from DB_Store import rankresume_pipeline


def api_error(code, message, status, details=None):
    return errors.APIError(
        code,
        {
            "error": {
                "code": code,
                "message": message,
                "status": status,
                "details": details or [],
            }
        },
    )


def quota_detail(quota_id):
    return {
        "@type": "type.googleapis.com/google.rpc.QuotaFailure",
        "violations": [
            {
                "quotaId": quota_id,
                "quotaMetric": "generativelanguage.googleapis.com/generate_content_requests",
            }
        ],
    }


class GeminiScorerTests(unittest.TestCase):
    def setUp(self):
        self.env_patcher = patch.dict(
            os.environ,
            {
                "GEMINI_API_KEY": "test-key",
                "GEMINI_MODEL": "models/gemini-3.1-flash-lite",
            },
        )
        self.env_patcher.start()
        self.addCleanup(self.env_patcher.stop)
        llm_scorer.reset_gemini_failure_state()

        self.client = MagicMock()
        self.client_patcher = patch.object(
            llm_scorer, "_get_gemini_client", return_value=self.client
        )
        self.client_patcher.start()
        self.addCleanup(self.client_patcher.stop)

    def evaluate(self, response_text=None, **kwargs):
        self.client.models.generate_content.return_value = SimpleNamespace(
            text=response_text
        )
        return llm_scorer.get_ollama_evaluation(
            {"title": "Analyst"},
            {"skills": ["Python"]},
            **kwargs,
        )

    def test_successful_gemini_json_response(self):
        result = self.evaluate('{"score": 85, "reason": "Python is listed."}')
        self.assertEqual(result, {"score": 85.0, "reason": "Python is listed."})
        call = self.client.models.generate_content.call_args.kwargs
        self.assertEqual(call["model"], "models/gemini-3.1-flash-lite")
        self.assertIn("JD JSON:", call["contents"])
        self.assertIn("Resume JSON:", call["contents"])
        self.assertEqual(call["config"].response_mime_type, "application/json")
        self.assertTrue(call["config"].automatic_function_calling.disable)
        self.assertEqual(call["config"].http_options.retry_options.attempts, 1)

    def test_429_retries_after_server_delay_then_succeeds(self):
        throttled = api_error(
            429,
            "rate limited",
            "RESOURCE_EXHAUSTED",
            [
                quota_detail("GenerateRequestsPerMinutePerModel-FreeTier"),
                {
                    "@type": "type.googleapis.com/google.rpc.RetryInfo",
                    "retryDelay": "2s",
                },
            ],
        )
        self.client.models.generate_content.side_effect = [
            throttled,
            SimpleNamespace(text='{"score": 85, "reason": "matched"}'),
        ]
        with patch.object(llm_scorer.time, "sleep") as sleep:
            result = llm_scorer.get_ollama_evaluation({}, {})
        self.assertEqual(result["score"], 85)
        self.assertEqual(self.client.models.generate_content.call_count, 2)
        self.assertGreaterEqual(sleep.call_args.args[0], 2.0)

    def test_persistent_429_stops_at_bounded_retry_limit_and_opens_breaker(self):
        throttled = api_error(
            429,
            "rate limited",
            "RESOURCE_EXHAUSTED",
            [quota_detail("GenerateRequestsPerMinutePerModel-FreeTier")],
        )
        self.client.models.generate_content.side_effect = throttled
        with patch.object(llm_scorer.time, "sleep"):
            self.assertIsNone(llm_scorer.get_ollama_evaluation({}, {}))
            self.assertIsNone(llm_scorer.get_ollama_evaluation({}, {}))
        self.assertEqual(
            self.client.models.generate_content.call_count,
            llm_scorer._MAX_RETRIES + 1,
        )

    def test_daily_quota_exhaustion_is_not_retried(self):
        exhausted = api_error(
            429,
            "daily quota exhausted",
            "RESOURCE_EXHAUSTED",
            [quota_detail("GenerateRequestsPerDayPerProjectPerModel-FreeTier")],
        )
        self.client.models.generate_content.side_effect = exhausted
        self.assertIsNone(llm_scorer.get_ollama_evaluation({}, {}))
        self.assertIsNone(llm_scorer.get_ollama_evaluation({}, {}))
        self.assertEqual(self.client.models.generate_content.call_count, 1)

    def test_503_retries_then_succeeds(self):
        unavailable = api_error(503, "temporarily unavailable", "UNAVAILABLE")
        self.client.models.generate_content.side_effect = [
            unavailable,
            SimpleNamespace(text='{"score": 72, "reason": "partial match"}'),
        ]
        with patch.object(llm_scorer.time, "sleep"):
            result = llm_scorer.get_ollama_evaluation({}, {})
        self.assertEqual(result["score"], 72)
        self.assertEqual(self.client.models.generate_content.call_count, 2)

    def test_invalid_key_and_invalid_model_are_not_retried(self):
        for exc in (
            api_error(403, "API key is invalid", "PERMISSION_DENIED"),
            api_error(404, "model not found", "NOT_FOUND"),
        ):
            with self.subTest(error=exc.code):
                llm_scorer.reset_gemini_failure_state()
                self.client.models.generate_content.reset_mock()
                self.client.models.generate_content.side_effect = exc
                self.assertIsNone(llm_scorer.get_ollama_evaluation({}, {}))
                self.assertEqual(self.client.models.generate_content.call_count, 1)

    def test_invalid_json_and_missing_score_return_none(self):
        for response_text in ("not JSON", '{"reason": "no score"}'):
            with self.subTest(response=response_text):
                llm_scorer.reset_gemini_failure_state()
                self.assertIsNone(self.evaluate(response_text))

    def test_empty_or_non_text_response_returns_none(self):
        for response_text in (None, 85, "", " \t\n "):
            with self.subTest(response=response_text):
                self.assertIsNone(self.evaluate(response_text))

    def test_public_scorer_signatures_remain_compatible(self):
        self.assertEqual(
            list(inspect.signature(llm_scorer.get_ollama_evaluation).parameters),
            ["jd_payload", "resume_payload", "model", "timeout"],
        )
        self.assertEqual(
            list(inspect.signature(llm_scorer.get_ollama_score).parameters),
            ["jd_payload", "resume_payload", "model"],
        )

    def test_client_factory_reuses_client_and_disables_sdk_retries(self):
        factory = self.client_patcher.temp_original
        factory.cache_clear()
        with patch.object(llm_scorer.genai, "Client") as client_factory:
            first = factory("test-key")
            second = factory("test-key")
        self.assertIs(first, second)
        client_factory.assert_called_once()
        options = client_factory.call_args.kwargs["http_options"]
        self.assertEqual(options.retry_options.attempts, 1)
        factory.cache_clear()


class ATSScoringModeTests(unittest.TestCase):
    def test_rule_only_fallback_is_identified(self):
        factors = SimpleNamespace(
            rule_based_score=80,
            to_dict=lambda: {"keyword_score": 80},
        )
        with (
            patch.object(ats_calculator, "evaluate_candidate_against_jd", return_value=factors),
            patch.object(ats_calculator, "get_ollama_evaluation", return_value=None),
        ):
            result = ats_calculator.compute_final_ats({}, {})
        self.assertEqual(result["final_ats_score"], 80)
        self.assertIsNone(result["llm_based_score"])
        self.assertEqual(result["scoring_mode"], "rule-only")

    def test_hybrid_score_is_unchanged(self):
        self.assertEqual(ats_calculator.combine_ats_scores(80, 90), 84)

    def test_unavailable_llm_falls_back_to_rule_score(self):
        self.assertEqual(ats_calculator.combine_ats_scores(80, None), 80)

    def test_score_all_candidates_persists_batched_llm_scores(self):
        class Cursor:
            def __init__(self, inserts):
                self.query = ""
                self.inserts = inserts

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def execute(self, query, params=None):
                self.query = query
                if "INSERT INTO ats_score" in query:
                    self.inserts.append(params)

            def fetchall(self):
                if "FROM job_description" in self.query:
                    return [(3, "Analyst", {"job_title": "Analyst"})]
                if "FROM candidate" in self.query:
                    return [
                        (12, "Candidate A", {"skills": ["Python"]}),
                        (13, "Candidate B", {"skills": ["SQL"]}),
                    ]
                return []

        inserts = []
        connection = MagicMock()
        connection.cursor.side_effect = lambda: Cursor(inserts)
        factors = SimpleNamespace(
            rule_based_score=80,
            keyword_score=70,
            similarity_score=75,
            title_score=80,
            experience_score=85,
            education_score=90,
            achievement_score=80,
        )
        with (
            patch.object(rankresume_pipeline, "reset_gemini_failure_state") as reset,
            patch.object(
                rankresume_pipeline,
                "get_batch_gemini_evaluations",
                return_value={
                    "12": {"score": 88.0, "reason": "matched"},
                    "13": {"score": 76.0, "reason": "partial match"},
                },
            ) as batch_scorer,
            patch.object(rankresume_pipeline, "get_ollama_score") as individual_scorer,
            patch.object(
                rankresume_pipeline,
                "evaluate_candidate_against_jd",
                return_value=factors,
            ),
        ):
            rankresume_pipeline.score_all_candidates(connection, jd_id=3)

        reset.assert_called_once_with()
        batch_scorer.assert_called_once_with(
            {"job_title": "Analyst"},
            [
                {"candidate_id": 12, "structured_data": {"skills": ["Python"]}},
                {"candidate_id": 13, "structured_data": {"skills": ["SQL"]}},
            ],
        )
        individual_scorer.assert_not_called()
        self.assertEqual([insert[-1] for insert in inserts], [88.0, 76.0])

    def test_failed_evaluation_replaces_old_llm_score_with_null(self):
        cursor = MagicMock()
        cursor.__enter__.return_value = cursor
        connection = MagicMock()
        connection.cursor.return_value = cursor
        factors = SimpleNamespace(
            rule_based_score=80,
            keyword_score=70,
            similarity_score=75,
            title_score=80,
            experience_score=85,
            education_score=90,
            achievement_score=80,
        )
        with (
            patch.object(rankresume_pipeline, "evaluate_candidate_against_jd", return_value=factors),
            patch.object(rankresume_pipeline, "get_ollama_score", return_value=None),
        ):
            rankresume_pipeline.store_candidate_ats_score(
                connection,
                12,
                3,
                {"job_title": "Analyst"},
                {"skills": ["Python"]},
            )
        cursor.execute.assert_any_call(
            "DELETE FROM ats_score WHERE candidate_id = %s AND jd_id = %s",
            (12, 3),
        )
        insert_call = next(
            call for call in cursor.execute.call_args_list
            if "INSERT INTO ats_score" in call.args[0]
        )
        self.assertIsNone(insert_call.args[1][-1])
        connection.commit.assert_called_once()

    def test_existing_llm_score_is_reused_unless_refresh_is_requested(self):
        class Cursor:
            def __init__(self):
                self.query = ""
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def execute(self, query, _params=None):
                self.query, self.params = query, _params

            def fetchall(self):
                if "FROM job_description" in self.query:
                    return [(3, "Analyst", {"job_title": "Analyst"})]
                if "FROM candidate" in self.query:
                    return [(12, "Candidate", {"skills": ["Python"]})]
                if "FROM ats_score" in self.query:
                    return [(12, 88.0)]
                return []

        connection = MagicMock()
        connection.cursor.side_effect = Cursor
        with (
            patch.dict(os.environ, {}, clear=False),
            patch.object(rankresume_pipeline, "reset_gemini_failure_state"),
            patch.object(rankresume_pipeline, "get_batch_gemini_evaluations") as batch_scorer,
            patch.object(rankresume_pipeline, "get_ollama_score") as scorer,
            patch.object(rankresume_pipeline, "store_candidate_ats_score", return_value=90),
        ):
            os.environ.pop("RANKRESUME_REFRESH_LLM_SCORES", None)
            results = rankresume_pipeline.score_all_candidates(connection, jd_id=3)
        batch_scorer.assert_not_called()
        scorer.assert_not_called()
        self.assertEqual(results[0]["scoring_mode"], "hybrid")

    def test_refresh_flag_invalidates_cached_llm_score(self):
        class Cursor:
            def __init__(self):
                self.query = ""
                self.params = None

            def __enter__(self):
                return self

            def __exit__(self, *_):
                return None

            def execute(self, query, _params=None):
                self.query, self.params = query, _params

            def fetchall(self):
                if "FROM job_description" in self.query:
                    return [(3, "Analyst", {"job_title": "Analyst"})]
                if "FROM candidate" in self.query:
                    return [(12, "Candidate", {"skills": ["Python"]})]
                return []

        connection = MagicMock()
        connection.cursor.side_effect = Cursor
        with (
            patch.dict(os.environ, {"RANKRESUME_REFRESH_LLM_SCORES": "1"}),
            patch.object(rankresume_pipeline, "reset_gemini_failure_state"),
            patch.object(rankresume_pipeline, "get_batch_gemini_evaluations", return_value={}) as batch_scorer,
            patch.object(rankresume_pipeline, "get_ollama_score", return_value=None) as scorer,
            patch.object(rankresume_pipeline, "store_candidate_ats_score", return_value=80),
        ):
            results = rankresume_pipeline.score_all_candidates(connection, jd_id=3)
        batch_scorer.assert_called_once()
        scorer.assert_not_called()
        self.assertEqual(results[0]["scoring_mode"], "rule-only")


if __name__ == "__main__":
    unittest.main()
