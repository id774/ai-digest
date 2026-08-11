#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/storage.py: Report persistence
#
#  Description:
#  Reports are stored on the file system, one directory per day, so that
#  no database is required and the archive can be inspected, backed up
#  or served by any web server:
#
#      <DATA_DIR>/<YYYY-MM-DD>/report.json   metadata and topics
#      <DATA_DIR>/<YYYY-MM-DD>/summary.png   composite daily image
#      <DATA_DIR>/<YYYY-MM-DD>/topic-N.png   topic illustrations
#
#  This module owns every path computation of the application. It also
#  validates the date strings it receives, because they arrive from URL
#  path segments in the Flask viewer and must never escape DATA_DIR.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.2 2026-08-11
#       Treat a syntactically valid report with an invalid structure as
#       corrupt instead of letting it raise while the viewer loads it.
#  v1.1 2026-08-02
#       Anchor the date pattern so that a trailing newline no longer
#       passes validation.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import json
import os
import re
from typing import Any, Dict, List, Optional

from ai_digest import Topic

# Report directories are named after their date and nothing else. The
# pattern is anchored with \A and \Z rather than ^ and $, because $ also
# matches in front of a trailing newline, which would let a date built
# from a URL segment name a directory of its own.
DATE_PATTERN = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

REPORT_FILENAME = "report.json"
SUMMARY_FILENAME = "summary.png"


def is_valid_date(date: str) -> bool:
    """ Return True when the string is a plain YYYY-MM-DD date. """
    return bool(DATE_PATTERN.match(date))


def report_dir(data_dir: str, date: str) -> str:
    """
    Return the directory of one report.

    Raises:
        ValueError: The date is not in YYYY-MM-DD form. This also
            prevents path traversal through crafted URLs.
    """
    if not is_valid_date(date):
        raise ValueError("invalid report date: {0}".format(date))
    return os.path.join(data_dir, date)


def ensure_report_dir(data_dir: str, date: str) -> str:
    """ Create and return the directory of one report. """
    path = report_dir(data_dir, date)
    os.makedirs(path, exist_ok=True)
    return path


def save_report(data_dir: str, date: str, topics: List[Topic],
                stats: Optional[Dict[str, Any]] = None) -> str:
    """
    Write report.json for one day.

    Args:
        data_dir: Root directory of the archive.
        date: Report date in YYYY-MM-DD form.
        topics: Topics to store, in display order.
        stats: Optional counters describing the run, stored as is.

    Returns:
        The path of the written JSON file.
    """
    path = os.path.join(ensure_report_dir(data_dir, date), REPORT_FILENAME)
    payload = {
        "date": date,
        "topics": [topic.to_dict() for topic in topics],
        "stats": stats or {},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def load_report(data_dir: str, date: str) -> Optional[Dict[str, Any]]:
    """
    Read one report.

    Returns:
        A dictionary with the keys 'date', 'topics' as Topic objects and
        'stats', or None when the report does not exist or is corrupt.
    """
    try:
        path = os.path.join(report_dir(data_dir, date), REPORT_FILENAME)
    except ValueError:
        return None
    if not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as handle:
            payload = json.load(handle)
    except (OSError, ValueError):
        return None
    if not isinstance(payload, dict):
        return None
    topics = payload.get("topics", [])
    stats = payload.get("stats", {})
    stored_date = payload.get("date", date)
    if (not isinstance(topics, list)
            or not all(isinstance(item, dict) for item in topics)
            or not isinstance(stats, dict)
            or not isinstance(stored_date, str)):
        return None
    try:
        loaded_topics = [Topic.from_dict(item) for item in topics]
    except (AttributeError, TypeError, ValueError):
        return None
    return {
        "date": stored_date,
        "topics": loaded_topics,
        "stats": stats,
    }


def list_dates(data_dir: str) -> List[str]:
    """ Return every stored report date, newest first. """
    if not os.path.isdir(data_dir):
        return []
    dates = [
        name for name in os.listdir(data_dir)
        if is_valid_date(name)
        and os.path.isfile(os.path.join(data_dir, name, REPORT_FILENAME))
    ]
    return sorted(dates, reverse=True)


def summary_image_path(data_dir: str, date: str) -> Optional[str]:
    """ Return the composite image path, or None when absent. """
    try:
        path = os.path.join(report_dir(data_dir, date), SUMMARY_FILENAME)
    except ValueError:
        return None
    return path if os.path.isfile(path) else None
