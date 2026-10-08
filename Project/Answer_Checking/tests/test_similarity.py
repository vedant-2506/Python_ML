import unittest

from Answer_Checking.similarity_scorer import clamp_score, cosine_similarity, similarity_score


class SimilarityTests(unittest.TestCase):
    def test_similarity_is_bounded(self):
        self.assertEqual(similarity_score([1, 0], [1, 0]), 100.0)
        self.assertEqual(similarity_score([1, 0], [0, 1]), 0.0)
        self.assertEqual(clamp_score(float("nan")), 0.0)
        self.assertEqual(cosine_similarity([], [1]), 0.0)
