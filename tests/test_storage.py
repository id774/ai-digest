#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_storage.py: Tests for ai_digest/storage.py
#
#  Description:
#  This test suite covers the persistence of a report and, above all,
#  the validation of the date strings that name its directory. Those
#  strings arrive from URL path segments in the Flask viewer, so a
#  crafted one has to end as a refusal rather than as a path outside
#  DATA_DIR: the cases below pin the refusal of a traversal, of a
#  loosely formatted date and of a trailing newline, and they pin that
#  a lookup answers with None instead of raising, so that the viewer
#  can answer 404 rather than a traceback.
#
#  The round trip cases cover the rest of the module: a report saved and
#  loaded again, and a directory that is not named after a date being
#  passed over when the archive is listed.
#
#  The publication cases cover publication_workspace(), which is what
#  keeps a report from becoming visible under its date directory before
#  it is complete: a staging directory is never listed as a date, a new
#  date only appears once its staging directory is published, a failure
#  before publication leaves no final directory at all, an existing
#  report survives a failure that happens while its replacement is
#  being staged or published, a successful replacement drops whatever
#  artifact only the previous report had, and a publication failure
#  that cannot be rolled back is reported rather than swallowed.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Running the tests:
#  Run the whole suite from the repository root:
#      python -m unittest discover -s tests
#  Run this module alone:
#      python -m unittest tests.test_storage
#
#  Test Cases:
#    - Accept a plain YYYY-MM-DD date.
#    - Reject anything that could escape the archive, a trailing newline included.
#    - Refuse a traversal in report_dir() with a ValueError.
#    - Return None from a lookup rather than raising on a crafted date.
#    - Accept a leap day in a leap year, and reject one shape-valid but
#      impossible calendar date after another - a non-leap Feb 29, Feb 31,
#      April 31, month 13, month 0, day 0 - from is_valid_date(),
#      report_dir(), a lookup and list_dates() alike.
#    - Return None for syntactically valid JSON with an invalid structure.
#    - Return None when the stored date does not match its directory.
#    - Save a report and load it back, listing its date in the archive.
#    - Ignore a directory that is not named after a date.
#    - Never list a staging directory as a report date.
#    - Publish a new date only once its staging directory is complete.
#    - Leave no final directory behind when staging a new date fails.
#    - Leave an existing report untouched when staging its replacement fails.
#    - Replace an existing report as a whole on a successful rerun, dropping
#      the artifact only the previous report had.
#    - Roll an existing report back when publishing its replacement fails.
#    - Report a publication failure whose rollback also fails, keeping the
#      backup rather than discarding it.
#    - Remove the staging directory, on a best effort basis, after a
#      generation failure.
#    - Copy an existing report's files into a staging directory.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.1 2026-09-06
#       Cover publication_workspace(), copy_existing_report(), the
#       failure-atomic publish/replace/rollback semantics they add, and
#       is_valid_date() rejecting an impossible calendar date.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import json
import os
import tempfile
import unittest
from unittest import mock

from ai_digest import Topic
from ai_digest import storage
from ai_digest.storage import (ReportPublicationError, copy_existing_report,
                               is_valid_date, list_dates, load_report,
                               publication_workspace, report_dir, save_report,
                               summary_image_path, write_report_json)

TRAVERSAL_DATES = (
    "../../etc",
    "2026-08-02/../..",
    "..%2F..%2Fetc",
    "2026-8-2",
    "20260802",
    "2026-08-02\n",
    "",
)

# Dates with the exact YYYY-MM-DD shape that name no real calendar day.
IMPOSSIBLE_CALENDAR_DATES = (
    "2026-02-29",  # 2026 is not a leap year
    "2026-02-30",
    "2026-02-31",
    "2026-04-31",  # April has 30 days
    "2026-13-01",  # no month 13
    "2026-00-01",  # no month 0
    "2026-01-00",  # no day 0
)


class DateValidationTest(unittest.TestCase):

    def test_accepts_a_plain_date(self):
        self.assertTrue(is_valid_date("2026-08-02"))

    def test_rejects_anything_that_could_escape_the_archive(self):
        for date in TRAVERSAL_DATES:
            with self.subTest(date=date):
                self.assertFalse(is_valid_date(date))

    def test_report_dir_refuses_a_traversal(self):
        for date in TRAVERSAL_DATES:
            with self.subTest(date=date):
                with self.assertRaises(ValueError):
                    report_dir("/tmp/archive", date)

    def test_lookups_return_none_instead_of_raising(self):
        # The viewer passes URL segments straight through; a crafted one
        # has to end as a 404, not as a traceback or a file outside the
        # archive.
        self.assertIsNone(load_report("/tmp/archive", "../../etc"))
        self.assertIsNone(summary_image_path("/tmp/archive", "../../etc"))

    def test_accepts_a_leap_day_in_a_leap_year(self):
        self.assertTrue(is_valid_date("2024-02-29"))

    def test_rejects_a_shape_valid_but_impossible_calendar_date(self):
        for date in IMPOSSIBLE_CALENDAR_DATES:
            with self.subTest(date=date):
                self.assertFalse(is_valid_date(date))

    def test_report_dir_refuses_an_impossible_calendar_date(self):
        for date in IMPOSSIBLE_CALENDAR_DATES:
            with self.subTest(date=date):
                with self.assertRaises(ValueError):
                    report_dir("/tmp/archive", date)

    def test_lookups_return_none_for_an_impossible_calendar_date(self):
        self.assertIsNone(load_report("/tmp/archive", "2026-02-31"))
        self.assertIsNone(summary_image_path("/tmp/archive", "2026-02-31"))


class RoundTripTest(unittest.TestCase):

    def test_returns_none_for_a_report_with_an_invalid_structure(self):
        invalid_payloads = (
            [],
            {"topics": {}},
            {"topics": [None]},
            {"topics": [{"bullets": None}]},
            {"stats": []},
            {"date": None},
        )
        with tempfile.TemporaryDirectory() as data_dir:
            directory = os.path.join(data_dir, "2026-08-02")
            os.makedirs(directory)
            path = os.path.join(directory, "report.json")

            for payload in invalid_payloads:
                with self.subTest(payload=payload):
                    with open(path, "w", encoding="utf-8") as handle:
                        json.dump(payload, handle)
                    self.assertIsNone(load_report(data_dir, "2026-08-02"))

    def test_returns_none_when_stored_date_does_not_match_directory(self):
        with tempfile.TemporaryDirectory() as data_dir:
            directory = os.path.join(data_dir, "2026-08-02")
            os.makedirs(directory)
            path = os.path.join(directory, "report.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"date": "2026-08-03", "topics": []}, handle)

            self.assertIsNone(load_report(data_dir, "2026-08-02"))

    def test_saves_and_loads_a_report(self):
        topic = Topic(category="テスト", title="見出し", bullets=["本文"],
                      sources=[{"title": "出典",
                                "url": "https://example.test/a"}])
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, "2026-08-02", [topic], {"topics": 1})

            loaded = load_report(data_dir, "2026-08-02")
            self.assertEqual("2026-08-02", loaded["date"])
            self.assertEqual("見出し", loaded["topics"][0].title)
            self.assertEqual(["2026-08-02"], list_dates(data_dir))

    def test_ignores_directories_that_are_not_dates(self):
        with tempfile.TemporaryDirectory() as data_dir:
            os.makedirs(os.path.join(data_dir, "scratch"))

            self.assertEqual([], list_dates(data_dir))

    def test_ignores_a_directory_named_after_an_impossible_calendar_date(self):
        with tempfile.TemporaryDirectory() as data_dir:
            directory = os.path.join(data_dir, "2026-02-31")
            os.makedirs(directory)
            path = os.path.join(directory, "report.json")
            with open(path, "w", encoding="utf-8") as handle:
                json.dump({"date": "2026-02-31", "topics": []}, handle)

            self.assertEqual([], list_dates(data_dir))


DATE = "2026-08-02"


def make_topic(marker: str = "本文") -> Topic:
    """ Return a minimal topic usable as staged or stored report content. """
    return Topic(category="テスト", title="見出し", bullets=[marker],
                sources=[{"title": "出典", "url": "https://example.test/a"}])


class PublicationWorkspaceTest(unittest.TestCase):
    """ publication_workspace() and the publish it performs on success. """

    def test_staging_directory_is_never_listed_as_a_date(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with publication_workspace(data_dir, DATE) as staging_dir:
                self.assertFalse(
                    is_valid_date(os.path.basename(staging_dir)))
                write_report_json(staging_dir, DATE, [make_topic()])
                self.assertEqual([], list_dates(data_dir))

    def test_publishes_a_new_date_only_once_complete(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with publication_workspace(data_dir, DATE) as staging_dir:
                self.assertFalse(os.path.isdir(report_dir(data_dir, DATE)))
                write_report_json(staging_dir, DATE, [make_topic()])

            self.assertEqual([DATE], list_dates(data_dir))
            loaded = load_report(data_dir, DATE)
            self.assertEqual("見出し", loaded["topics"][0].title)

    def test_new_date_failure_leaves_no_final_directory(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with self.assertRaises(RuntimeError):
                with publication_workspace(data_dir, DATE) as staging_dir:
                    write_report_json(staging_dir, DATE, [make_topic()])
                    raise RuntimeError("generation failed")

            self.assertFalse(os.path.isdir(report_dir(data_dir, DATE)))
            self.assertEqual([], list_dates(data_dir))

    def test_staging_is_removed_on_a_best_effort_basis_after_failure(self):
        with tempfile.TemporaryDirectory() as data_dir:
            captured = {}
            with self.assertRaises(RuntimeError):
                with publication_workspace(data_dir, DATE) as staging_dir:
                    captured["staging_dir"] = staging_dir
                    raise RuntimeError("generation failed")

            self.assertFalse(os.path.exists(captured["staging_dir"]))
            # Nothing but the archive root itself remains.
            self.assertEqual([], os.listdir(data_dir))

    def test_new_date_publication_failure_leaves_nothing_behind(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=OSError("simulated disk failure")):
                with self.assertRaises(ReportPublicationError):
                    with publication_workspace(data_dir, DATE) as staging_dir:
                        write_report_json(staging_dir, DATE, [make_topic()])

            self.assertFalse(os.path.isdir(report_dir(data_dir, DATE)))
            self.assertEqual([], list_dates(data_dir))
            self.assertEqual([], os.listdir(data_dir))

    def test_existing_report_survives_a_staging_failure(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, DATE, [make_topic("old")], {"run": 1})
            before = load_report(data_dir, DATE)

            with self.assertRaises(RuntimeError):
                with publication_workspace(data_dir, DATE) as staging_dir:
                    write_report_json(staging_dir, DATE, [make_topic("new")],
                                      {"run": 2})
                    raise RuntimeError("generation failed")

            after = load_report(data_dir, DATE)
            self.assertEqual(before["stats"], after["stats"])
            self.assertEqual("old", after["topics"][0].bullets[0])

    def test_successful_replacement_drops_stale_old_artifacts(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, DATE, [make_topic("old")], {"run": 1})
            stale_path = os.path.join(report_dir(data_dir, DATE),
                                      "topic-1.png")
            with open(stale_path, "wb") as handle:
                handle.write(b"stale image data")

            with publication_workspace(data_dir, DATE) as staging_dir:
                write_report_json(staging_dir, DATE, [make_topic("new")],
                                  {"run": 2})

            self.assertFalse(os.path.isfile(stale_path))
            loaded = load_report(data_dir, DATE)
            self.assertEqual({"run": 2}, loaded["stats"])
            self.assertEqual("new", loaded["topics"][0].bullets[0])
            self.assertEqual([DATE], list_dates(data_dir))

    def test_rolls_back_when_publishing_a_replacement_fails(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, DATE, [make_topic("old")], {"run": 1})
            before = load_report(data_dir, DATE)

            original_rename = os.rename
            calls = []

            def flaky_rename(src, dst):
                calls.append((src, dst))
                # The first rename moves the existing report aside; the
                # second, moving the new one into place, is the one that
                # fails here so the rollback path is exercised.
                if len(calls) == 2:
                    raise OSError("simulated disk failure")
                return original_rename(src, dst)

            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=flaky_rename):
                with self.assertRaises(ReportPublicationError):
                    with publication_workspace(data_dir, DATE) as staging_dir:
                        write_report_json(staging_dir, DATE,
                                          [make_topic("new")], {"run": 2})

            after = load_report(data_dir, DATE)
            self.assertEqual(before["stats"], after["stats"])
            self.assertEqual("old", after["topics"][0].bullets[0])
            self.assertEqual([DATE], list_dates(data_dir))
            # The rollback succeeded, so no backup directory is left behind.
            leftover = [name for name in os.listdir(data_dir)
                       if name.startswith(storage.BACKUP_PREFIX)]
            self.assertEqual([], leftover)

    def test_a_rollback_failure_is_reported_and_the_backup_is_kept(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, DATE, [make_topic("old")], {"run": 1})

            original_rename = os.rename
            calls = []

            def always_flaky_rename(src, dst):
                calls.append((src, dst))
                if len(calls) == 1:
                    # Move the existing report aside, as usual.
                    return original_rename(src, dst)
                # Both putting the new report in place and rolling the
                # old one back fail, so neither tree ends up named DATE.
                raise OSError("simulated disk failure")

            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=always_flaky_rename):
                with self.assertRaises(ReportPublicationError):
                    with publication_workspace(data_dir, DATE) as staging_dir:
                        write_report_json(staging_dir, DATE,
                                          [make_topic("new")], {"run": 2})

            # A rollback failure must not be mistaken for success: the
            # previous report is not silently back in place...
            self.assertFalse(os.path.isdir(report_dir(data_dir, DATE)))
            # ...and its backup copy is kept rather than discarded, so
            # the evidence needed to recover it by hand still exists.
            backups = [name for name in os.listdir(data_dir)
                      if name.startswith(storage.BACKUP_PREFIX)]
            self.assertEqual(1, len(backups))


class CopyExistingReportTest(unittest.TestCase):

    def test_copies_every_file_of_a_stored_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, DATE, [make_topic()], {"run": 1})
            source_dir = report_dir(data_dir, DATE)
            with open(os.path.join(source_dir, "topic-1.png"), "wb") as handle:
                handle.write(b"illustration bytes")

            with tempfile.TemporaryDirectory() as staging_dir:
                copy_existing_report(data_dir, DATE, staging_dir)

                self.assertTrue(os.path.isfile(
                    os.path.join(staging_dir, "report.json")))
                with open(os.path.join(staging_dir, "topic-1.png"), "rb") as h:
                    self.assertEqual(b"illustration bytes", h.read())
                # The source tree is untouched by the copy.
                self.assertTrue(os.path.isfile(
                    os.path.join(source_dir, "topic-1.png")))


if __name__ == "__main__":
    unittest.main()
