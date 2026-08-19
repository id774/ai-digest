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
#    - Return None for syntactically valid JSON with an invalid structure.
#    - Return None when the stored date does not match its directory.
#    - Save a report and load it back, listing its date in the archive.
#    - Ignore a directory that is not named after a date.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import json
import os
import tempfile
import unittest

from ai_digest import Topic
from ai_digest.storage import (is_valid_date, list_dates, load_report,
                               report_dir, save_report, summary_image_path)

TRAVERSAL_DATES = (
    "../../etc",
    "2026-08-02/../..",
    "..%2F..%2Fetc",
    "2026-8-2",
    "20260802",
    "2026-08-02\n",
    "",
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


if __name__ == "__main__":
    unittest.main()
