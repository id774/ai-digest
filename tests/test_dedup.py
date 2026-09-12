#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_dedup.py: Tests for title normalization and deduplication
#
#  Description:
#  This suite pins the mechanical title normalization and deduplicate
#  contract described in doc/BASIC_DESIGN.md: NFKC normalization, case
#  folding, and dropping everything that is neither a letter nor a
#  digit, in the sense of Unicode's own letter and digit categories
#  rather than a fixed allowlist of scripts. It checks that this still
#  absorbs ASCII case, punctuation and whitespace differences, full
#  width forms, and accented Latin, while no longer discarding distinct
#  non-ASCII letters such as Greek that give two titles different
#  meanings.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Running the tests:
#  Run the whole suite from the repository root:
#      python -m unittest discover -s tests
#  Run this module alone:
#      python -m unittest tests.test_dedup
#
#  Test Cases:
#    - ASCII case, punctuation and whitespace differences normalize to
#      the same key.
#    - Full width Latin letters and digits normalize to the same key as
#      their half width ASCII equivalents.
#    - "Straße" and "STRASSE" normalize to the same key after case
#      folding.
#    - Titles distinguished only by Greek letters keep different keys
#      instead of collapsing to the same one.
#    - Two entries with such distinct titles both survive dedup.
#    - An exact duplicate URL is dropped to a single entry.
#    - Of two entries with an equal normalized title, the first
#      occurrence survives.
#    - Two different URLs whose titles normalize to an empty key are
#      not treated as duplicates of each other.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.0 2026-09-12
#       Initial release.
#
########################################################################

import unittest

from ai_digest import Entry
from ai_digest.dedup import deduplicate, normalize_title


def make_entry(title: str, url: str) -> Entry:
    """ Build a minimal news entry for dedup tests. """
    return Entry(source_type="news", title=title, url=url)


class NormalizeTitleTests(unittest.TestCase):
    """ Tests for normalize_title() alone. """

    def test_case_punctuation_and_whitespace_are_absorbed(self):
        self.assertEqual(
            normalize_title("Model Improves, Results!"),
            normalize_title("  model improves results  "),
        )

    def test_fullwidth_forms_match_ascii(self):
        self.assertEqual(
            normalize_title("Ｍｏｄｅｌ４"),
            normalize_title("Model4"),
        )

    def test_eszett_matches_ss_after_casefold(self):
        self.assertEqual(normalize_title("Straße"), normalize_title("STRASSE"))

    def test_distinct_greek_letters_are_preserved(self):
        alpha_key = normalize_title("Model α improves")
        beta_key = normalize_title("Model β improves")
        self.assertNotEqual(alpha_key, beta_key)


class DeduplicateTests(unittest.TestCase):
    """ Tests for deduplicate()'s contract. """

    def test_distinct_greek_titles_both_survive(self):
        entries = [
            make_entry("Model α", "https://example.com/alpha"),
            make_entry("Model β", "https://example.com/beta"),
        ]
        kept = deduplicate(entries)
        self.assertEqual(len(kept), 2)
        self.assertEqual({entry.url for entry in kept}, {
            "https://example.com/alpha",
            "https://example.com/beta",
        })

    def test_exact_duplicate_url_is_dropped(self):
        entries = [
            make_entry("First report", "https://example.com/story"),
            make_entry("Different title, same story",
                       "https://example.com/story"),
        ]
        kept = deduplicate(entries)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].title, "First report")

    def test_first_occurrence_survives_on_title_match(self):
        entries = [
            make_entry("Model Improves Results", "https://example.com/a"),
            make_entry("model improves results!",
                       "https://example.com/b"),
        ]
        kept = deduplicate(entries)
        self.assertEqual(len(kept), 1)
        self.assertEqual(kept[0].url, "https://example.com/a")

    def test_empty_normalized_titles_are_not_merged(self):
        entries = [
            make_entry("!!!", "https://example.com/x"),
            make_entry("\U0001F600", "https://example.com/y"),
        ]
        kept = deduplicate(entries)
        self.assertEqual(len(kept), 2)
        self.assertEqual({entry.url for entry in kept}, {
            "https://example.com/x",
            "https://example.com/y",
        })


if __name__ == "__main__":
    unittest.main()
