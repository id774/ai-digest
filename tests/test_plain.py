#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest

from ai_digest import Entry
from ai_digest.analyzer import plain


def _entry(title, published, summary="", source_type="news", origin=""):
    return Entry(source_type=source_type, title=title,
                 url="https://example.test/{0}".format(title),
                 summary=summary, published=published, origin=origin)


class PlainSummarizeTest(unittest.TestCase):

    def test_returns_newest_first(self):
        topics = plain.summarize([
            _entry("old", "2026-08-01T00:00:00+00:00"),
            _entry("new", "2026-08-02T00:00:00+00:00"),
        ], 6)

        self.assertEqual(["new", "old"], [topic.title for topic in topics])

    def test_honours_max_topics(self):
        entries = [_entry(str(index), "2026-08-0{0}T00:00:00+00:00".format(
            index)) for index in range(1, 6)]

        self.assertEqual(2, len(plain.summarize(entries, 2)))

    def test_splits_a_summary_into_bullets(self):
        topics = plain.summarize([
            _entry("a", "2026-08-02T00:00:00+00:00",
                   summary="First one. Second one. Third one."),
        ], 6)

        self.assertEqual(["First one.", "Second one.", "Third one."],
                         topics[0].bullets)

    def test_keeps_at_most_four_bullets(self):
        summary = " ".join("S{0}.".format(index) for index in range(10))
        topics = plain.summarize([
            _entry("a", "2026-08-02T00:00:00+00:00", summary=summary),
        ], 6)

        self.assertEqual(plain.MAX_BULLETS, len(topics[0].bullets))

    def test_truncates_a_long_bullet(self):
        topics = plain.summarize([
            _entry("a", "2026-08-02T00:00:00+00:00", summary="x" * 400),
        ], 6)

        bullet = topics[0].bullets[0]
        self.assertEqual(plain.BULLET_CHARS, len(bullet))
        self.assertTrue(bullet.endswith("…"))

    def test_falls_back_on_the_title_without_a_summary(self):
        topics = plain.summarize([
            _entry("only a title", "2026-08-02T00:00:00+00:00"),
        ], 6)

        self.assertEqual(["only a title"], topics[0].bullets)

    def test_category_comes_from_the_origin(self):
        topics = plain.summarize([
            _entry("paper", "2026-08-02T00:00:00+00:00",
                   source_type="paper", origin="arXiv cs.AI"),
            _entry("news", "2026-08-01T00:00:00+00:00", origin="Feed Title"),
        ], 6)

        self.assertEqual(["arXiv cs.AI", "Feed Title"],
                         [topic.category for topic in topics])

    def test_category_falls_back_when_the_origin_is_empty(self):
        topics = plain.summarize([
            _entry("paper", "2026-08-02T00:00:00+00:00", source_type="paper"),
            _entry("news", "2026-08-01T00:00:00+00:00"),
        ], 6)

        self.assertEqual(["arXiv", "News"],
                         [topic.category for topic in topics])

    def test_every_topic_cites_its_entry(self):
        topics = plain.summarize([
            _entry("a", "2026-08-02T00:00:00+00:00"),
        ], 6)

        self.assertEqual([{"title": "a", "url": "https://example.test/a"}],
                         topics[0].sources)

    def test_no_entry_yields_no_topic(self):
        self.assertEqual([], plain.summarize([], 6))


if __name__ == "__main__":
    unittest.main()
