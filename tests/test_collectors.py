#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import unittest
from datetime import datetime, timedelta, timezone
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


@unittest.skipUnless(hasattr(time, "tzset"), "requires time.tzset")
class LookBackWindowTest(unittest.TestCase):
    """ The age filter must not depend on the timezone of the host. """

    def setUp(self):
        self.saved_tz = os.environ.get("TZ")
        os.environ["TZ"] = "Asia/Tokyo"
        time.tzset()

    def tearDown(self):
        if self.saved_tz is None:
            del os.environ["TZ"]
        else:
            os.environ["TZ"] = self.saved_tz
        time.tzset()

    def entry(self, hours_ago):
        moment = datetime.now(timezone.utc) - timedelta(hours=hours_ago)
        return SimpleNamespace(
            link="https://example.test/a",
            title="Title",
            summary="Summary sentence.",
            published_parsed=moment.timetuple(),
        )

    def test_reads_the_timestamp_as_utc(self):
        moment = datetime(2026, 8, 3, 6, 0, tzinfo=timezone.utc)
        raw_entry = SimpleNamespace(published_parsed=moment.timetuple())

        for module in (arxiv, news_rss):
            self.assertEqual(moment, module._entry_datetime(raw_entry))

    def test_keeps_an_entry_inside_the_window(self):
        # Read as local time, an entry 20 hours old looks 29 hours old
        # in Asia/Tokyo and falls out of the 24 hour window.
        raw_entry = self.entry(20)

        for module in (arxiv, news_rss):
            published = module._entry_datetime(raw_entry)
            age = datetime.now(timezone.utc) - published
            self.assertLess(age, timedelta(hours=24))


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
