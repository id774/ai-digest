#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_render_command.py: Tests for the render command of cli.py
#
#  Description:
#  This test suite covers the window a rebuilt image announces. The
#  render command draws a report that was collected earlier, possibly
#  under a different LOOKBACK_HOURS, so it reads the window out of the
#  statistics the run stored rather than out of the configuration it is
#  running under. A report written before that value was recorded has
#  nothing to read, and only then does the configuration decide.
#
#  The second case closes the loop from the other side: a run has to
#  store the window before render can read it, so the demo command is
#  driven with the drawing stages replaced and only its stored
#  statistics are examined.
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
#      python -m unittest tests.test_render_command
#
#  Test Cases:
#    - Use the window recorded by the run that collected the report.
#    - Fall back on the configuration for a report that recorded none.
#    - Report a missing date as a failed run.
#    - Record the window a demo run ran with.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt (the command line module imports the whole pipeline)
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

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
