#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/__init__.py: Package marker and shared data structures
#
#  Description:
#  ai_digest is the implementation package of the ai-digest application.
#  It collects AI related papers and news once a day, summarizes them in
#  Japanese with the Claude API, resolves an illustration for every
#  topic and renders both an HTML report and a single composite PNG.
#
#  This module keeps the package level metadata and the dataclasses
#  shared by the collectors, the analyzer and the renderers:
#
#      Entry            - one collected item (paper or news article)
#      Topic            - one curated block of the daily report
#      CollectionResult - what one collector obtained, and from how
#                         many sources it failed to obtain it
#
#  Entry and Topic provide to_dict()/from_dict() so that reports can be
#  serialized as plain JSON without any external dependency.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#
#  Version History:
#  v1.2 2026-08-03
#       Add CollectionResult, which carries the per source outcome of a
#       collector next to its entries.
#  v1.1 2026-08-02
#       Add is_safe_url(), the shared link scheme guard.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

__version__ = "1.1"

# Schemes accepted for any link that ends up in a report. Collected
# links come from third party feeds and are rendered as anchors, where
# 'javascript:' and 'data:' would execute in the reader's browser;
# autoescaping does not help there, since the value is a valid
# attribute, not markup.
SAFE_URL_SCHEMES = ("http", "https")

# Palette used to colorize categories. Categories are produced freely by
# the language model, so a color is derived from the category name hash
# instead of a fixed mapping. The palette is intentionally small and
# high contrast so that white text stays readable on every entry.
CATEGORY_PALETTE = (
    "#1f4e79",
    "#7b2d26",
    "#2f6b3a",
    "#5b3d88",
    "#8a6a12",
    "#1b5f6b",
    "#7a3b6b",
    "#3c4a5a",
)


def is_safe_url(url: str) -> bool:
    """
    Return True when a URL may be published as a link.

    Only absolute http and https URLs pass. Everything else is refused,
    including relative references, since a link stored in a report is
    rendered both by the viewer and by the standalone HTML, where the
    document it is opened from is not a reliable base.
    """
    if not url:
        return False
    try:
        parsed = urlparse(url.strip())
    except ValueError:  # malformed IPv6 literals and the like
        return False
    return parsed.scheme.lower() in SAFE_URL_SCHEMES and bool(parsed.netloc)


def safe_url(url: str) -> str:
    """
    Return a URL safe to place in an href, or '#' when it is not.

    This is the rendering side of is_safe_url(): reports written before
    the collectors started filtering links, or edited by hand, are
    neutralized at display time instead of being trusted.
    """
    return url if is_safe_url(url) else "#"


def category_color(category: str) -> str:
    """
    Return a stable color for a category name.

    The same category always maps to the same palette entry within and
    across reports, because the index is derived from a deterministic
    hash of the name. Python's builtin hash() is not used since it is
    salted per process.
    """
    digest = 0
    for char in category:
        digest = (digest * 131 + ord(char)) & 0xFFFFFFFF
    return CATEGORY_PALETTE[digest % len(CATEGORY_PALETTE)]


@dataclass
class Entry:
    """
    One item collected from arXiv or from an RSS feed.

    Attributes:
        source_type: Either 'paper' or 'news'.
        title: Original title, usually English.
        url: Canonical URL of the item.
        summary: Original abstract or feed summary, plain text.
        published: ISO 8601 timestamp of publication, UTC.
        origin: Human readable origin, e.g. 'arXiv cs.AI' or the feed title.
    """

    source_type: str
    title: str
    url: str
    summary: str = ""
    published: str = ""
    origin: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """ Return a JSON serializable representation. """
        return {
            "source_type": self.source_type,
            "title": self.title,
            "url": self.url,
            "summary": self.summary,
            "published": self.published,
            "origin": self.origin,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Entry":
        """ Rebuild an Entry from its dictionary representation. """
        return cls(
            source_type=data.get("source_type", "news"),
            title=data.get("title", ""),
            url=data.get("url", ""),
            summary=data.get("summary", ""),
            published=data.get("published", ""),
            origin=data.get("origin", ""),
        )


@dataclass
class CollectionResult:
    """
    Outcome of one collection pass, entries plus how they were obtained.

    An empty entry list has several causes that a caller must be able to
    tell apart: no source configured, every source unreachable, or
    sources that answered normally with nothing recent to offer. The
    counters below record which of these happened.

    Attributes:
        entries: The entries kept, newest first.
        sources_total: Sources the collector was asked to read.
        sources_failed: Sources that could not be read or parsed.
        items_seen: Items the readable sources offered, before filtering.
        items_outside_window: Items dropped for being too old.
        failures: One 'source: reason' line per unreadable source.
    """

    entries: List[Entry] = field(default_factory=list)
    sources_total: int = 0
    sources_failed: int = 0
    items_seen: int = 0
    items_outside_window: int = 0
    failures: List[str] = field(default_factory=list)

    @property
    def sources_read(self) -> int:
        """ Return the number of sources that answered and parsed. """
        return self.sources_total - self.sources_failed

    def merge(self, other: "CollectionResult") -> "CollectionResult":
        """ Return the combined outcome of two collection passes. """
        return CollectionResult(
            entries=self.entries + other.entries,
            sources_total=self.sources_total + other.sources_total,
            sources_failed=self.sources_failed + other.sources_failed,
            items_seen=self.items_seen + other.items_seen,
            items_outside_window=(self.items_outside_window
                                  + other.items_outside_window),
            failures=self.failures + other.failures,
        )


@dataclass
class Topic:
    """
    One curated block of the daily report.

    A topic groups one or more collected entries that cover the same
    story, and carries the Japanese summary produced by the language
    model together with the illustration resolved for it.

    Attributes:
        category: Free form Japanese category label chosen by the model.
        title: Japanese headline of the topic.
        bullets: Two to four Japanese bullet points.
        sources: List of {'title': ..., 'url': ...} dictionaries.
        image: File name of the topic image inside the report directory.
        image_credit: Where the image came from, or 'generated'.
    """

    category: str
    title: str
    bullets: List[str] = field(default_factory=list)
    sources: List[Dict[str, str]] = field(default_factory=list)
    image: Optional[str] = None
    image_credit: str = ""

    @property
    def color(self) -> str:
        """ Return the color assigned to this topic's category. """
        return category_color(self.category)

    def to_dict(self) -> Dict[str, Any]:
        """ Return a JSON serializable representation. """
        return {
            "category": self.category,
            "title": self.title,
            "bullets": list(self.bullets),
            "sources": [dict(source) for source in self.sources],
            "image": self.image,
            "image_credit": self.image_credit,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Topic":
        """ Rebuild a Topic from its dictionary representation. """
        return cls(
            category=data.get("category", ""),
            title=data.get("title", ""),
            bullets=list(data.get("bullets", [])),
            sources=[dict(source) for source in data.get("sources", [])],
            image=data.get("image"),
            image_credit=data.get("image_credit", ""),
        )
