#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/collectors/news_rss.py: News feed collector
#
#  Description:
#  This module reads the RSS or Atom feeds configured through
#  NEWS_FEED_URLS and returns the articles published during the look
#  back window.
#
#  Feeds are fetched with requests rather than handed to feedparser
#  directly, so that the HTTP timeout and the User-Agent of the
#  application apply to every source. Feeds that are unreachable, that
#  time out or that cannot be parsed contribute no entries and never
#  abort the daily batch. The returned CollectionResult records how many
#  feeds failed and how many articles the readable ones offered, so that
#  the caller can tell a broken network from a quiet look back window.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - feedparser, requests
#
#  Version History:
#  v1.5 2026-11-08
#       Keep only entries published within the look back window up to the
#       collection time, and drop one whose time cannot be represented.
#  v1.4 2026-09-22
#       Cap the read body at MAX_COLLECTOR_RESPONSE_BYTES, failing an
#       oversized feed the same way an unreachable one fails.
#  v1.3 2026-09-08
#       Fetch configured feeds only over HTTPS, including redirects.
#  v1.2 2026-08-03
#       Read the parsed timestamps as UTC, which is what feedparser returns, instead of as local time.
#       Return a CollectionResult describing the outcome of every feed instead of a bare entry list.
#  v1.1 2026-08-02
#       Drop entries whose link is not an http or https URL.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import calendar
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import urlparse

import feedparser
import requests

from ai_digest import CollectionResult, Entry, is_safe_url
from ai_digest.transport import https_get, read_capped_content

# Strip HTML markup from feed summaries; feeds mix plain text, escaped
# HTML and full articles, and only the readable text is useful here.
TAG_PATTERN = re.compile(r"<[^>]+>")

# Feed summaries can be whole articles. Only the beginning is needed to
# let the language model judge and summarize the item.
SUMMARY_LIMIT = 1200

logger = logging.getLogger(__name__)


def _utc_now() -> datetime:
    """ Return the collection reference time as an aware UTC datetime. """
    return datetime.now(timezone.utc)


def _plain_text(html: str) -> str:
    """ Remove tags and collapse whitespace of a feed summary. """
    return " ".join(TAG_PATTERN.sub(" ", html).split())[:SUMMARY_LIMIT]


def _entry_datetime(raw_entry) -> datetime:
    """
    Return the publication time of a feed entry as an aware datetime.

    feedparser exposes the parsed struct_time in UTC, so it is turned
    into an epoch with calendar.timegm(). time.mktime() would read it as
    local time and shift every entry by the offset of the host, which
    narrows or widens the look back window. Feeds that omit both
    published and updated timestamps are treated as epoch old, which
    makes the age filter drop them.

    Raises:
        ValueError: The parsed time is outside the range a datetime can
            represent, such as year 0 or year 10000.
    """
    parsed = getattr(raw_entry, "published_parsed", None)
    if parsed is None:
        parsed = getattr(raw_entry, "updated_parsed", None)
    if parsed is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    try:
        return datetime.fromtimestamp(calendar.timegm(parsed),
                                      tz=timezone.utc)
    except (ValueError, OverflowError, OSError) as error:
        raise ValueError("unrepresentable publication time: {0}".format(error))


def _feed_origin(parsed_feed, url: str) -> str:
    """ Return the feed title, falling back on its host name. """
    title = getattr(parsed_feed.feed, "title", "")
    if title:
        return " ".join(title.split())
    return _host(url)


def _host(url: str) -> str:
    """ Return the netloc of url without any userinfo, or '' if unparsable. """
    try:
        return urlparse(url).netloc.rpartition("@")[2]
    except ValueError:
        return ""


def _has_userinfo(url: str) -> bool:
    """ Return True when url embeds userinfo, even an empty one. """
    try:
        return "@" in urlparse(url).netloc
    except ValueError:
        # An unparsable URL cannot be told apart from one with userinfo,
        # and the failure that follows would quote it, so treat it as one.
        return "@" in url


def collect(feed_urls: List[str], lookback_hours: int, timeout: int = 15,
            user_agent: str = "ai-digest") -> CollectionResult:
    """
    Collect recent news articles from RSS or Atom feeds.

    Args:
        feed_urls: Feed URLs to read.
        lookback_hours: Only articles published within this many hours
            up to now are kept; a future-dated article is dropped.
        timeout: HTTP timeout in seconds.
        user_agent: User-Agent header sent to the feed hosts.

    Returns:
        A CollectionResult whose entries have source_type 'news' and are
        ordered newest first. Duplicate URLs across feeds are reported
        once. The counters tell how many feeds failed and how many
        articles the readable ones offered.
    """
    now = _utc_now()
    threshold = now - timedelta(hours=lookback_hours)
    result = CollectionResult(sources_total=len(feed_urls))
    entries: List[Entry] = []
    seen_urls = set()

    for url in feed_urls:
        if _has_userinfo(url):
            # Never send, log or report a URL carrying credentials.
            shown = "{0} (credentials in URL)".format(_host(url) or "feed")
            logger.warning("feed refused for %s", shown)
            result.sources_failed += 1
            result.failures.append("{0}: credentials in URL are not "
                                   "allowed".format(shown))
            continue
        try:
            with https_get(url, timeout, user_agent, stream=True) as response:
                response.raise_for_status()
                content = read_capped_content(response)
        except requests.RequestException as error:
            logger.warning("feed request failed for %s: %s", url, error)
            result.sources_failed += 1
            result.failures.append("{0}: {1}".format(url, error))
            continue

        parsed_feed = feedparser.parse(content)
        if not parsed_feed.entries and getattr(parsed_feed, "bozo", 0):
            error = getattr(parsed_feed, "bozo_exception",
                            "unknown parse error")
            logger.warning("feed unusable for %s: %s", url, error)
            result.sources_failed += 1
            result.failures.append("{0}: unparsable feed: {1}".format(
                url, error))
            continue

        origin = _feed_origin(parsed_feed, url)
        result.items_seen += len(parsed_feed.entries)
        for raw_entry in parsed_feed.entries:
            try:
                published = _entry_datetime(raw_entry)
            except ValueError:
                logger.warning("dropping entry with unrepresentable "
                               "publication time from %s", origin)
                continue
            if published > now or published < threshold:
                # Feed order is not guaranteed, so keep scanning the
                # remaining items instead of breaking out of the loop.
                result.items_outside_window += 1
                continue
            link = getattr(raw_entry, "link", "")
            if not link or link in seen_urls:
                continue
            if not is_safe_url(link):
                logger.warning("dropping entry with unusable link %s", link)
                continue
            seen_urls.add(link)
            summary = getattr(raw_entry, "summary", "")
            entries.append(Entry(
                source_type="news",
                title=" ".join(getattr(raw_entry, "title", "").split()),
                url=link,
                summary=_plain_text(summary),
                published=published.isoformat(),
                origin=origin,
            ))

    entries.sort(key=lambda item: item.published, reverse=True)
    result.entries = entries
    logger.info("collected %d news articles from %d of %d feeds "
                "(%d articles offered, look back %d hours)", len(entries),
                result.sources_read, result.sources_total, result.items_seen,
                lookback_hours)
    return result
