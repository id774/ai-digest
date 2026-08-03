#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import time
import unittest
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest import mock

import cli
from ai_digest import CollectionResult
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


def _collect_news(links, lookback_hours=24):
    """ Run the news collector over stubbed feed entries. """
    parsed = SimpleNamespace(
        feed=SimpleNamespace(title="Feed"),
        entries=[_feed_entry(link) for link in links],
    )
    response = mock.Mock(content=b"<rss/>")
    response.raise_for_status = mock.Mock()
    with mock.patch.object(news_rss.requests, "get", return_value=response):
        with mock.patch.object(news_rss.feedparser, "parse",
                               return_value=parsed):
            return news_rss.collect(["https://feed.test/rss"], lookback_hours)


class NewsLinkFilterTest(unittest.TestCase):

    def collect(self, links):
        return _collect_news(links).entries

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
                               return_value=(raw_entries, "")):
            with mock.patch.object(time, "sleep"):
                return arxiv.collect(["cs.AI"], 10, 24).entries

    def test_keeps_http_links(self):
        entries = self.collect(["https://arxiv.org/abs/2601.00001"])

        self.assertEqual(1, len(entries))

    def test_drops_a_script_link(self):
        with self.assertLogs(arxiv.logger, "WARNING") as logged:
            entries = self.collect(["javascript:alert(1)"])

        self.assertEqual([], entries)
        self.assertIn("unusable link", logged.output[0])


class CollectionOutcomeTest(unittest.TestCase):
    """ An empty pass must say whether the sources could be read. """

    def test_reports_a_failed_feed(self):
        error = news_rss.requests.ConnectionError("name resolution failed")
        with mock.patch.object(news_rss.requests, "get", side_effect=error):
            with self.assertLogs(news_rss.logger, "WARNING"):
                result = news_rss.collect(["https://feed.test/rss"], 24)

        self.assertEqual([], result.entries)
        self.assertEqual(1, result.sources_total)
        self.assertEqual(1, result.sources_failed)
        self.assertEqual(0, result.items_seen)
        self.assertIn("name resolution failed", result.failures[0])

    def test_reports_a_read_feed_without_recent_entry(self):
        with mock.patch.object(news_rss, "_entry_datetime",
                               return_value=datetime(2020, 1, 1,
                                                     tzinfo=timezone.utc)):
            result = _collect_news(["https://example.test/a"])

        self.assertEqual([], result.entries)
        self.assertEqual(0, result.sources_failed)
        self.assertEqual(1, result.items_seen)
        self.assertEqual(1, result.items_outside_window)

    def test_reports_a_failed_arxiv_category(self):
        with mock.patch.object(arxiv, "_fetch_category",
                               return_value=([], "timed out")):
            with mock.patch.object(time, "sleep"):
                result = arxiv.collect(["cs.AI", "cs.LG"], 10, 24)

        self.assertEqual(2, result.sources_failed)
        self.assertEqual(0, result.sources_read)
        self.assertEqual(["arXiv cs.AI: timed out", "arXiv cs.LG: timed out"],
                         result.failures)

    def test_merges_two_passes(self):
        papers = CollectionResult(sources_total=2, sources_failed=1,
                                  items_seen=5, items_outside_window=5,
                                  failures=["arXiv cs.AI: timed out"])
        news = CollectionResult(sources_total=3, items_seen=7,
                                items_outside_window=7)

        merged = papers.merge(news)

        self.assertEqual(5, merged.sources_total)
        self.assertEqual(1, merged.sources_failed)
        self.assertEqual(4, merged.sources_read)
        self.assertEqual(12, merged.items_seen)
        self.assertEqual(["arXiv cs.AI: timed out"], merged.failures)


class EmptyCollectionMessageTest(unittest.TestCase):
    """ The message must name the cause instead of listing them all. """

    def describe(self, **kwargs):
        return cli.describe_empty_collection(CollectionResult(**kwargs), 48)

    def test_no_source_configured(self):
        message = self.describe(sources_total=0)

        self.assertIn("no source configured", message)

    def test_every_source_failed(self):
        message = self.describe(sources_total=2, sources_failed=2,
                                failures=["a: timed out", "b: timed out"])

        self.assertIn("all 2 sources failed", message)
        self.assertIn("network connection", message)
        self.assertIn("a: timed out", message)

    def test_sources_answered_with_nothing_recent(self):
        message = self.describe(sources_total=4, items_seen=120,
                                items_outside_window=120)

        self.assertIn("4 of 4 sources answered and offered 120 items", message)
        self.assertIn("last 48 hours", message)
        self.assertNotIn("network connection", message)

    def test_sources_answered_empty(self):
        message = self.describe(sources_total=4)

        self.assertIn("returned no item at all", message)
        self.assertIn("ARXIV_CATEGORIES", message)

    def test_mentions_the_failed_sources_of_a_partial_pass(self):
        message = self.describe(sources_total=4, sources_failed=1,
                                items_seen=30, items_outside_window=30,
                                failures=["b: timed out"])

        self.assertIn("3 of 4 sources answered", message)
        self.assertIn("the remaining 1 could not be read", message)
        self.assertIn("b: timed out", message)


if __name__ == "__main__":
    unittest.main()
