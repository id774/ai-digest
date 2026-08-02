#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
