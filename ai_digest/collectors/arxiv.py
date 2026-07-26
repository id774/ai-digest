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
#  category yields no entries instead of aborting the daily batch.
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
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import List
from urllib.parse import urlencode

import feedparser
import requests

from ai_digest import Entry

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

    feedparser exposes the parsed struct_time in UTC. Entries without a
    usable timestamp are reported as the epoch so that the age filter
    discards them.
    """
    parsed = getattr(raw_entry, "published_parsed", None)
    if parsed is None:
        parsed = getattr(raw_entry, "updated_parsed", None)
    if parsed is None:
        return datetime.fromtimestamp(0, tz=timezone.utc)
    return datetime.fromtimestamp(time.mktime(parsed), tz=timezone.utc)


def _fetch_category(category: str, max_results: int, timeout: int,
                    user_agent: str) -> List:
    """
    Fetch the newest entries of a single arXiv category.

    An empty list is returned when the request fails, so that the
    caller can continue with the remaining categories.
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
        return []
    return feedparser.parse(response.content).entries


def collect(categories: List[str], max_results: int, lookback_hours: int,
            timeout: int = 15, user_agent: str = "ai-digest") -> List[Entry]:
    """
    Collect recent arXiv papers.

    Args:
        categories: arXiv category identifiers such as 'cs.AI'.
        max_results: Maximum entries requested per category.
        lookback_hours: Only papers newer than this age are kept.
        timeout: HTTP timeout in seconds.
        user_agent: User-Agent header sent to arXiv.

    Returns:
        A list of Entry objects with source_type 'paper', newest first.
        Papers cross listed in several requested categories appear once.
    """
    threshold = datetime.now(timezone.utc) - timedelta(hours=lookback_hours)
    entries: List[Entry] = []
    seen_urls = set()

    for index, category in enumerate(categories):
        if index > 0:
            time.sleep(REQUEST_INTERVAL)
        for raw_entry in _fetch_category(category, max_results, timeout,
                                         user_agent):
            published = _entry_datetime(raw_entry)
            if published < threshold:
                # Entries are sorted newest first, so everything that
                # follows in this category is older as well.
                break
            url = getattr(raw_entry, "link", "")
            if not url or url in seen_urls:
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
    logger.info("collected %d arXiv papers", len(entries))
    return entries
