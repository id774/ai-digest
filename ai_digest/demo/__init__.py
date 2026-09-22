#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/demo/__init__.py: Bundled demo report
#
#  Description:
#  This subpackage backs 'python cli.py demo', which builds a report
#  from data shipped with the repository instead of from the network.
#  It exists so that a fresh clone can show what a finished report looks
#  like before an API key is configured.
#
#  Three stages of the pipeline are replaced, because they need outbound
#  access. Collection is replaced by the 'entries' array of
#  sample_input.json, summarization by its 'build_report' object, which
#  holds representative arguments from an API-backed build_report tool
#  call, and illustration draws a local fallback card for every topic
#  instead of scraping one. Everything downstream is the pipeline
#  itself: the payload is validated by summarizer.to_topics(), and the
#  caller stores and renders the result as usual.
#
#  The sample is data, not a recording of one API response, so a demo
#  run costs nothing, needs no key and renders identically everywhere.
#  See doc/DEMO.md for how it differs from a live report.
#
#  Author: id774 (More info: https://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.1 2026-09-23
#       Validate a custom sample's shape and types before building from
#       it, instead of letting a malformed one crash with a raw exception.
#  v1.0 2026-07-28
#       Initial release.
#
########################################################################

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ai_digest import Entry, Topic, is_safe_url
from ai_digest.analyzer.summarizer import to_topics
from ai_digest.storage import is_valid_date

# Sample shipped with the repository, used when no other file is given.
SAMPLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "sample_input.json")

__all__ = ["SAMPLE_PATH", "load_sample", "build_topics"]


def load_sample(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Read a demo sample.

    Args:
        path: Sample to read, or None for the bundled one.

    Returns:
        The parsed sample.

    Raises:
        OSError: The file cannot be read.
        ValueError: The file is not valid JSON.
    """
    with open(path or SAMPLE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def _validate_sample(sample: Any) -> None:
    """
    Raise ValueError when sample is not a usable demo payload.

    A custom --input sample is untrusted structured input just because
    it is not the bundled, checked-in one, even though it comes from
    local disk rather than the network: without this, a malformed shape
    would reach Entry.from_dict() or is_valid_date() as an uncaught
    AttributeError or TypeError instead of the ordinary, logged command
    failure every other bad sample already produces. build_report is
    not checked here: to_topics() already validates it by type, field
    by field, the same way it validates a live tool call's answer.
    """
    if not isinstance(sample, dict):
        raise ValueError("the sample must be a JSON object")

    date = sample.get("date")
    if not isinstance(date, str) or not is_valid_date(date):
        raise ValueError(
            "the sample's 'date' must be a real YYYY-MM-DD date")

    entries = sample.get("entries")
    if not isinstance(entries, list) or not entries:
        raise ValueError("the sample's 'entries' must be a non-empty list")

    for index, item in enumerate(entries):
        if not isinstance(item, dict):
            raise ValueError(
                "entries[{0}] must be an object".format(index))
        title = item.get("title", "")
        if not isinstance(title, str) or not title.strip():
            raise ValueError(
                "entries[{0}].title must be a nonblank string"
                .format(index))
        url = item.get("url", "")
        if not isinstance(url, str) or not is_safe_url(url):
            raise ValueError(
                "entries[{0}].url must be an absolute http or https URL"
                .format(index))
        if "source_type" in item and item["source_type"] not in (
                "paper", "news"):
            raise ValueError(
                "entries[{0}].source_type must be 'paper' or 'news'"
                .format(index))
        for field in ("summary", "published", "origin"):
            if field in item and not isinstance(item[field], str):
                raise ValueError(
                    "entries[{0}].{1} must be a string"
                    .format(index, field))


def build_topics(max_topics: int, path: Optional[str] = None
                 ) -> Tuple[str, List[Topic], int]:
    """
    Build the topics of a demo report.

    The sample's shape is validated before anything is built from it,
    and the stored build_report payload then goes through the same
    conversion as a real tool call, so a malformed sample is rejected
    exactly as a malformed model answer would be.

    Args:
        max_topics: Maximum number of topics to keep.
        path: Sample to read, or None for the bundled one.

    Returns:
        The report date, the topics without images yet, and the number
        of entries the sample stands in for.

    Raises:
        KeyError: The sample lacks 'build_report'.
        OSError: The file cannot be read.
        ValueError: The file is not valid JSON, or its shape is not a
            usable demo payload.
    """
    sample = load_sample(path)
    _validate_sample(sample)
    entries: List[Entry] = [Entry.from_dict(item)
                            for item in sample["entries"]]
    topics = to_topics(sample["build_report"], entries, max_topics)
    return sample["date"], topics, len(entries)
