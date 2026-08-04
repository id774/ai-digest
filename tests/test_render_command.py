#!/usr/bin/env python
# -*- coding: utf-8 -*-

import tempfile
import unittest
from dataclasses import replace
from unittest import mock

import cli
from ai_digest import Topic
from ai_digest.storage import save_report
from config import Config

DATE = "2026-08-04"


class RenderLookbackTest(unittest.TestCase):
    """ A rebuilt image announces the window the run collected. """

    def render(self, stats, configured_hours=24):
        topic = Topic(category="分類", title="見出し", bullets=["箇条書き。"],
                      sources=[{"title": "t", "url": "https://example.test/"}])
        with tempfile.TemporaryDirectory() as directory:
            save_report(directory, DATE, [topic], stats)
            config = replace(Config(), data_dir=directory,
                             lookback_hours=configured_hours)
            args = cli.parse_args(["render", DATE])
            with mock.patch.object(cli.compose_image, "compose") as compose:
                with mock.patch.object(cli.build, "write_report_html"):
                    code = cli.command_render(args, config)
        return code, compose

    def test_uses_the_window_recorded_by_the_run(self):
        code, compose = self.render({"lookback_hours": 72})

        self.assertEqual(0, code)
        self.assertEqual(72, compose.call_args.args[4])

    def test_falls_back_on_the_configuration_for_an_older_report(self):
        code, compose = self.render({"model": "demo"})

        self.assertEqual(0, code)
        self.assertEqual(24, compose.call_args.args[4])

    def test_reports_a_missing_date(self):
        with tempfile.TemporaryDirectory() as directory:
            config = replace(Config(), data_dir=directory)
            args = cli.parse_args(["render", "2026-01-01"])
            with self.assertLogs("ai_digest.cli", "ERROR"):
                self.assertEqual(1, cli.command_render(args, config))


class RecordedWindowTest(unittest.TestCase):
    """ A run has to store the window before render can read it. """

    def test_demo_records_the_window_it_ran_with(self):
        # Only the stored statistics are of interest, so the stages
        # that draw are replaced rather than exercised again here.
        with tempfile.TemporaryDirectory() as directory:
            config = replace(Config(), data_dir=directory, lookback_hours=48,
                             max_topics=1)
            args = cli.parse_args(["demo"])
            with mock.patch.object(cli, "attach_images"):
                with mock.patch.object(cli.compose_image, "compose"):
                    with mock.patch.object(cli.build, "write_report_html"):
                        self.assertEqual(0, cli.command_demo(args, config))

            stored = cli.load_report(directory, cli.demo.load_sample()["date"])

        self.assertEqual(48, stored["stats"]["lookback_hours"])


if __name__ == "__main__":
    unittest.main()
