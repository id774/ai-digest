#!/usr/bin/env python
# -*- coding: utf-8 -*-

import time
import unittest
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest import mock

from ai_digest.collectors import arxiv, news_rss


def _recent_struct_time():
    """ Return a struct_time inside any sane look back window. """
    return datetime.now(timezone.utc).timetuple()


def _feed_entry(link):
    return SimpleNamespace(
        link=link,
        title="Title",
        summary="Summary sentence.",
        published_parsed=_recent_struct_time(),
    )


class NewsLinkFilterTest(unittest.TestCase):

    def collect(self, links):
        parsed = SimpleNamespace(
            feed=SimpleNamespace(title="Feed"),
            entries=[_feed_entry(link) for link in links],
        )
        response = mock.Mock(content=b"<rss/>")
        response.raise_for_status = mock.Mock()
        with mock.patch.object(news_rss.requests, "get",
                               return_value=response):
            with mock.patch.object(news_rss.feedparser, "parse",
                                   return_value=parsed):
                return news_rss.collect(["https://feed.test/rss"], 24)

    def test_keeps_http_links(self):
        entries = self.collect(["https://example.test/a"])

        self.assertEqual(1, len(entries))
        self.assertEqual("https://example.test/a", entries[0].url)

    def test_drops_a_script_link(self):
        with self.assertLogs(news_rss.logger, "WARNING") as logged:
            entries = self.collect(["javascript:alert(1)"])

        self.assertEqual([], entries)
        self.assertIn("unusable link", logged.output[0])

    def test_drops_only_the_unsafe_entry(self):
        with self.assertLogs(news_rss.logger, "WARNING"):
            entries = self.collect([
                "javascript:alert(1)",
                "https://example.test/good",
            ])

        self.assertEqual(["https://example.test/good"],
                         [entry.url for entry in entries])


class ArxivLinkFilterTest(unittest.TestCase):

    def collect(self, links):
        raw_entries = [_feed_entry(link) for link in links]
        with mock.patch.object(arxiv, "_fetch_category",
                               return_value=raw_entries):
            with mock.patch.object(time, "sleep"):
                return arxiv.collect(["cs.AI"], 10, 24)

    def test_keeps_http_links(self):
        entries = self.collect(["https://arxiv.org/abs/2601.00001"])

        self.assertEqual(1, len(entries))

    def test_drops_a_script_link(self):
        with self.assertLogs(arxiv.logger, "WARNING") as logged:
            entries = self.collect(["javascript:alert(1)"])

        self.assertEqual([], entries)
        self.assertIn("unusable link", logged.output[0])


if __name__ == "__main__":
    unittest.main()
