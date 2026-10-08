import unittest

from Answer_Checking.concept_matcher import concept_coverage, parse_concepts


class ConceptMatchingTests(unittest.TestCase):
    def test_synonym_is_covered(self):
        self.assertEqual(concept_coverage(["parent class"], "A base class provides inherited behavior."), 100.0)

    def test_missing_concepts_and_irrelevant_text_score_low(self):
        self.assertEqual(concept_coverage(["parent class", "child class"], "A network protocol routes packets."), 0.0)
        self.assertEqual(parse_concepts('["SQL", "joins"]'), ["SQL", "joins"])
