#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import tempfile
import unittest

from ai_digest import demo


class BundledSampleTest(unittest.TestCase):

    def setUp(self):
        self.sample = demo.load_sample()

    def test_ships_a_readable_sample(self):
        self.assertTrue(os.path.isfile(demo.SAMPLE_PATH))
        self.assertIn("date", self.sample)
        self.assertTrue(self.sample["entries"])
        self.assertTrue(self.sample["build_report"]["topics"])

    def test_builds_every_topic_of_the_sample(self):
        expected = len(self.sample["build_report"]["topics"])

        date, topics, collected = demo.build_topics(expected)

        self.assertEqual(self.sample["date"], date)
        self.assertEqual(expected, len(topics))
        self.assertEqual(len(self.sample["entries"]), collected)

    def test_keeps_every_topic_citable_and_illustrable(self):
        _date, topics, _collected = demo.build_topics(6)

        for topic in topics:
            self.assertTrue(topic.category)
            self.assertTrue(topic.title)
            self.assertTrue(topic.bullets)
            self.assertTrue(topic.sources)
            for source in topic.sources:
                self.assertTrue(source["url"].startswith("https://"))

    def test_honours_the_topic_limit(self):
        _date, topics, _collected = demo.build_topics(2)

        self.assertEqual(2, len(topics))


class CustomSampleTest(unittest.TestCase):

    def build(self, payload, max_topics=6):
        with tempfile.TemporaryDirectory() as directory:
            path = os.path.join(directory, "sample.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle)
            return demo.build_topics(max_topics, path)

    def test_reads_a_sample_given_by_path(self):
        date, topics, collected = self.build({
            "date": "2026-01-02",
            "entries": [{
                "source_type": "paper",
                "title": "A paper",
                "url": "https://example.test/paper",
            }],
            "build_report": {"topics": [{
                "category": "分類",
                "title": "見出し",
                "bullets": ["箇条書き。"],
                "source_indexes": [0],
            }]},
        })

        self.assertEqual("2026-01-02", date)
        self.assertEqual(1, collected)
        self.assertEqual("見出し", topics[0].title)

    def test_drops_a_topic_citing_no_usable_entry(self):
        payload = {
            "date": "2026-01-02",
            "entries": [{
                "source_type": "paper",
                "title": "A paper",
                "url": "https://example.test/paper",
            }],
            "build_report": {"topics": [{
                "category": "分類",
                "title": "見出し",
                "bullets": ["箇条書き。"],
                "source_indexes": [7],
            }]},
        }

        # The dropped topic is logged, which assertLogs both asserts on
        # and keeps out of the test output.
        with self.assertLogs("ai_digest.analyzer.summarizer", "WARNING"):
            _date, topics, _collected = self.build(payload)

        self.assertEqual([], topics)

    def test_rejects_a_sample_without_entries(self):
        with self.assertRaises(KeyError):
            self.build({"date": "2026-01-02", "build_report": {"topics": []}})


if __name__ == "__main__":
    unittest.main()
