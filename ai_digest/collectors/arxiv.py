#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/collectors/arxiv.py: arXiv paper collector
#
#  Description:
#  This module queries the public arXiv Atom API and returns the papers
#  announced during the look back window for the configured categories.
#
#  The API is documented at https://info.arxiv.org/help/api/index.html.
#  Results are requested sorted by submission date in descending order,
#  so the age filter can stop as soon as older entries appear. arXiv
#  asks clients to stay well below one request every three seconds; the
#  collector issues a single request per category and sleeps in between.
#
#  Network and parsing failures are logged and swallowed: a failing
#  category yields no entries instead of aborting the daily batch. The
#  returned CollectionResult records how many categories failed and how
#  many papers the readable ones offered, so that the caller can tell an
#  unreachable API from a window that simply holds nothing.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - feedparser, requests
#
#  Version History:
#  v1.2 2026-08-03
#       Read the parsed timestamps as UTC, which is what feedparser
#       returns, instead of as local time. Return a CollectionResult
#       describing the outcome of every category instead of a bare
#       entry list.
#  v1.1 2026-08-02
#       Drop entries whose link is not an http or https URL.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import calendar
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List, Tuple
from urllib.parse import urlencode

import feedparser
import requests

from ai_digest import CollectionResult, Entry, is_safe_url

API_ENDPOINT = "http://export.arxiv.org/api/query"

# Delay between two consecutive API requests, in seconds, to respect the
# rate limit recommended by arXiv.
REQUEST_INTERVAL = 3.0

logger = logging.getLogger(__name__)


def _normalize_text(text: str) -> str:
    """ Collapse the whitespace of an abstract into a single line. """
    return " ".join(text.split())


def _entry_datetime(raw_entry) -> datetime:
    """
    Return the publication time of a feed entry as an aware datetime.

    feedparser exposes the parsed struct_time in UTC, so it is turned
    into an epoch with calendar.timegm(). time.mktime() would read it as
    local time and shift every entry by the offset of the host, which
    narrows or widens the look back window. Entries without a usable
    timestamp are reported as the epoch so that the age filter discards
    them.
    """
    parsed = getattr(raw_entry, "published_parsed", None)
    if parsed is None:
        parsed = getattr(raw_entry, "updated_parsed", None)
    if parsed is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromtimestamp(calendar.timegm(parsed), tz=timezone.utc)


def _fetch_category(category: str, max_results: int, timeout: int,
                    user_agent: str) -> Tuple[List, str]:
    """
    Fetch the newest entries of a single arXiv category.

    Returns:
        The raw feed entries and an empty string, or an empty list and
        the reason the category could not be read, so that the caller
        can continue with the remaining categories and still report why
        this one contributed nothing.
    """
    query = urlencode({
        "search_query": "cat:{0}".format(category),
        "start": 0,
        "max_results": max_results,
        "sortBy": "submittedDate",
        "sortOrder": "descending",
    })
    url = "{0}?{1}".format(API_ENDPOINT, query)
    try:
        response = requests.get(
            url, timeout=timeout, headers={"User-Agent": user_agent}
        )
        response.raise_for_status()
    except requests.RequestException as error:
        logger.warning("arXiv request failed for %s: %s", category, error)
        return [], "{0}".format(error)
    parsed = feedparser.parse(response.content)
    if not parsed.entries and getattr(parsed, "bozo", 0):
        error = getattr(parsed, "bozo_exception", "unknown parse error")
        logger.warning("arXiv response unusable for %s: %s", category, error)
        return [], "unparsable response: {0}".format(error)
    return parsed.entries, ""


def collect(categories: List[str], max_results: int, lookback_hours: int,
            timeout: int = 15,
            user_agent: str = "ai-digest") -> CollectionResult:
    """
    Collect recent arXiv papers.

    Args:
        categories: arXiv category identifiers such as 'cs.AI'.
        max_results: Maximum entries requested per category.
        lookback_hours: Only papers newer than this age are kept.
        timeout: HTTP timeout in seconds.
        user_agent: User-Agent header sent to arXiv.

    Returns:
        A CollectionResult whose entries have source_type 'paper' and
        are ordered newest first. Papers cross listed in several
        requested categories appear once. The counters tell how many
        categories failed and how many papers the readable ones offered.
    """
    threshold = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    result = CollectionResult(sources_total=len(categories))
    entries: List[Entry] = []
    seen_urls = set()

    for index, category in enumerate(categories):
        if index > 0:
            time.sleep(REQUEST_INTERVAL)
        raw_entries, failure = _fetch_category(category, max_results, timeout,
                                               user_agent)
        if failure:
            result.sources_failed += 1
            result.failures.append("arXiv {0}: {1}".format(category, failure))
            continue
        result.items_seen += len(raw_entries)
        for position, raw_entry in enumerate(raw_entries):
            published = _entry_datetime(raw_entry)
            if published < threshold:
                # Entries are sorted newest first, so everything that
                # follows in this category is older as well.
                result.items_outside_window += len(raw_entries) - position
                break
            url = getattr(raw_entry, "link", "")
            if not url or url in seen_urls:
                continue
            if not is_safe_url(url):
                logger.warning("dropping paper with unusable link %s", url)
                continue
            seen_urls.add(url)
            entries.append(Entry(
                source_type="paper",
                title=_normalize_text(getattr(raw_entry, "title", "")),
                url=url,
                summary=_normalize_text(getattr(raw_entry, "summary", "")),
                published=published.isoformat(),
                origin="arXiv {0}".format(category),
            ))

    entries.sort(key=lambda item: item.published, reverse=True)
    result.entries = entries
    logger.info("collected %d arXiv papers from %d of %d categories "
                "(%d papers offered, look back %d hours)", len(entries),
                result.sources_read, result.sources_total, result.items_seen,
                lookback_hours)
    return result
