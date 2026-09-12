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
#  A report is built in a staging directory beside the archive dates,
#  through publication_workspace(), and is only made visible under
#  <DATA_DIR>/<date> once every artifact it needs is written. Publishing
#  a date that already holds a complete report moves the previous tree
#  aside first, so that a failure while putting the new one in place can
#  restore it; the previous tree is discarded only once the new one has
#  taken its place. Neither directory is named like a date, so neither
#  is ever listed or served as a report of its own.
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
#  v1.5 2026-09-12
#       Reject stored topic field types that downstream renderers cannot consume.
#  v1.4 2026-09-06
#       Publish reports atomically and reject impossible calendar dates.
#  v1.3 2026-08-19
#       Reject a report whose stored date does not match its directory.
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

import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
from datetime import datetime
from typing import Any, Dict, Iterator, List, Optional

from ai_digest import Topic

logger = logging.getLogger(__name__)

# Report directories are named after their date and nothing else. The
# pattern is anchored with \A and \Z rather than ^ and $, because $ also
# matches in front of a trailing newline, which would let a date built
# from a URL segment name a directory of its own.
DATE_PATTERN = re.compile(r"\A\d{4}-\d{2}-\d{2}\Z")

REPORT_FILENAME = "report.json"
SUMMARY_FILENAME = "summary.png"

# Staging and backup directories live beside the date directories, under
# DATA_DIR, so that publishing them is a same-filesystem rename rather
# than a cross-filesystem copy. Both prefixes start with a character
# DATE_PATTERN never matches, and neither is a plain YYYY-MM-DD name, so
# list_dates() and every date-validated lookup pass over them.
STAGING_PREFIX = ".ai-digest-staging-"
BACKUP_PREFIX = ".ai-digest-backup-"


class ReportPublicationError(RuntimeError):
    """ Raised when a staged report cannot be published as a whole. """


def is_valid_date(date: str) -> bool:
    """
    Return True when the string names a real Gregorian calendar date.

    The exact YYYY-MM-DD shape is checked first, anchored so that a
    trailing newline or a path traversal segment cannot pass. Only a
    string with that shape is then parsed for calendar validity, so a
    date that merely looks right - '2026-02-31', a non-leap
    '2026-02-29', an out-of-range month - is refused as well.
    """
    if not DATE_PATTERN.match(date):
        return False
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        return False
    return True


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


def write_report_json(directory: str, date: str, topics: List[Topic],
                      stats: Optional[Dict[str, Any]] = None) -> str:
    """
    Write report.json directly into an existing directory.

    Unlike save_report(), the caller supplies the directory itself,
    which is what lets a report be built in a staging directory instead
    of the final archive location.

    Args:
        directory: Directory report.json is written into.
        date: Report date in YYYY-MM-DD form, stored inside the file.
        topics: Topics to store, in display order.
        stats: Optional counters describing the run, stored as is.

    Returns:
        The path of the written JSON file.
    """
    path = os.path.join(directory, REPORT_FILENAME)
    payload = {
        "date": date,
        "topics": [topic.to_dict() for topic in topics],
        "stats": stats or {},
    }
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
    return path


def save_report(data_dir: str, date: str, topics: List[Topic],
                stats: Optional[Dict[str, Any]] = None) -> str:
    """
    Write report.json for one day directly under <data_dir>/<date>.

    Args:
        data_dir: Root directory of the archive.
        date: Report date in YYYY-MM-DD form.
        topics: Topics to store, in display order.
        stats: Optional counters describing the run, stored as is.

    Returns:
        The path of the written JSON file.
    """
    return write_report_json(ensure_report_dir(data_dir, date), date, topics,
                             stats)


def _remove_best_effort(path: str) -> None:
    """ Delete a staging or backup directory, logging rather than raising. """
    try:
        shutil.rmtree(path)
    except OSError as error:
        logger.warning("could not remove %s: %s", path, error)


def _publish(staging_dir: str, final_dir: str, date: str) -> None:
    """
    Replace final_dir with the complete staging_dir, as a whole.

    A date that is not yet published is a plain rename. One that is
    already published is moved aside under a backup name first, so that
    a failure renaming the new tree into place can restore it; the old
    tree is discarded only once the new one has taken its place.

    Raises:
        ReportPublicationError: The new report could not be published.
            When the previous report existed, the exception says whether
            it was restored.
    """
    if not os.path.exists(final_dir):
        try:
            os.rename(staging_dir, final_dir)
        except OSError as error:
            _remove_best_effort(staging_dir)
            raise ReportPublicationError(
                "could not publish the new report for {0}: {1}".format(
                    date, error)) from error
        return

    data_dir = os.path.dirname(final_dir)
    backup_dir = os.path.join(data_dir, "{0}{1}-{2}".format(
        BACKUP_PREFIX, date, os.path.basename(staging_dir)))
    try:
        os.rename(final_dir, backup_dir)
    except OSError as error:
        _remove_best_effort(staging_dir)
        raise ReportPublicationError(
            "could not move the existing report for {0} aside: {1}".format(
                date, error)) from error

    try:
        os.rename(staging_dir, final_dir)
    except OSError as error:
        try:
            os.rename(backup_dir, final_dir)
        except OSError as rollback_error:
            raise ReportPublicationError(
                "publishing the report for {0} failed ({1}), and the "
                "previous report could not be restored ({2}); it is kept "
                "at {3}".format(date, error, rollback_error,
                               backup_dir)) from rollback_error
        _remove_best_effort(staging_dir)
        raise ReportPublicationError(
            "publishing the report for {0} failed and the previous report "
            "was restored: {1}".format(date, error)) from error
    else:
        _remove_best_effort(backup_dir)


@contextlib.contextmanager
def publication_workspace(data_dir: str, date: str) -> Iterator[str]:
    """
    Yield an empty staging directory to build one report in.

    The directory is created beside the date directories, on the same
    file system as DATA_DIR, so that publishing it is a rename rather
    than a cross-filesystem copy. Its name never matches DATE_PATTERN,
    so it is invisible to list_dates() and to every date-validated
    lookup even while the block below is still running.

    On a clean exit of the block, the staging directory replaces
    <data_dir>/<date> as a whole: a date not yet published appears for
    the first time, and one that already holds a complete report is
    replaced by it, with no artifact of the previous report left
    standing. Raising out of the block leaves an existing final report
    exactly as it was and removes the staging directory on a best
    effort basis; that cleanup failure never replaces the original
    error.

    Args:
        data_dir: Root directory of the archive.
        date: Report date in YYYY-MM-DD form.

    Yields:
        The path of the staging directory to build the report in.

    Raises:
        ValueError: The date is not in YYYY-MM-DD form.
        ReportPublicationError: The complete staging directory could
            not be published.
    """
    final_dir = report_dir(data_dir, date)
    os.makedirs(data_dir, exist_ok=True)
    staging_dir = tempfile.mkdtemp(prefix=STAGING_PREFIX, dir=data_dir)
    try:
        yield staging_dir
    except Exception:
        _remove_best_effort(staging_dir)
        raise
    else:
        _publish(staging_dir, final_dir, date)


def copy_existing_report(data_dir: str, date: str, staging_dir: str) -> None:
    """
    Copy a stored report's files into a staging directory.

    Used by 're-render' to bring the authoritative report.json and the
    topic illustrations of an already published report into a staging
    directory, without ever reading from or writing to the final
    directory while the derived artifacts are being rebuilt.

    Args:
        data_dir: Root directory of the archive.
        date: Report date in YYYY-MM-DD form.
        staging_dir: Existing, empty staging directory to copy into.

    Raises:
        ValueError: The date is not in YYYY-MM-DD form.
    """
    source_dir = report_dir(data_dir, date)
    for name in os.listdir(source_dir):
        source_path = os.path.join(source_dir, name)
        dest_path = os.path.join(staging_dir, name)
        if os.path.isdir(source_path):
            shutil.copytree(source_path, dest_path)
        else:
            shutil.copy2(source_path, dest_path)


def _is_valid_topic_payload(data: Dict[str, Any]) -> bool:
    """
    Return True when a stored topic dict has types Topic.from_dict() and
    the renderers built on it can consume.

    Every field here is optional: a payload missing one is accepted so
    that Topic.from_dict()'s own defaults still apply. A field that is
    present, including one explicitly set to null, is checked against
    the type the renderer requires - 'image' is the only field allowed
    to be null, since Topic.image itself is Optional[str]. What is not
    checked is any semantic property such as length, emptiness or
    content: that validation belongs to the analyzer, not to this
    defensive reader.
    """
    if "category" in data and not isinstance(data["category"], str):
        return False

    if "title" in data and not isinstance(data["title"], str):
        return False

    if "bullets" in data:
        bullets = data["bullets"]
        if not isinstance(bullets, list):
            return False
        if not all(isinstance(bullet, str) for bullet in bullets):
            return False

    if "sources" in data:
        sources = data["sources"]
        if not isinstance(sources, list):
            return False
        for source in sources:
            if not isinstance(source, dict):
                return False
            if "title" in source and not isinstance(source["title"], str):
                return False
            if "url" in source and not isinstance(source["url"], str):
                return False

    if "image" in data and data["image"] is not None \
            and not isinstance(data["image"], str):
        return False

    if "image_credit" in data and not isinstance(data["image_credit"], str):
        return False

    return True


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
            or not isinstance(stored_date, str)
            or stored_date != date):
        return None
    if not all(_is_valid_topic_payload(item) for item in topics):
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
