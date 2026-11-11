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
#  A demo report is identified by its 'model' field rather than by
#  whether a numeric lookback_hours happens to be present, since one
#  stored before that distinction existed still carries a stale one.
#
#  The last case closes the loop from the other side: a run has to
#  store the window before render can read it, so the demo command is
#  driven with the drawing stages replaced and only its stored
#  statistics are examined.
#
#  Author: id774 (More info: https://id774.net)
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
#    - Name a demo report by its model field even with a stale numeric
#      lookback_hours left over from before that rule existed.
#    - Report a missing date as a failed run.
#    - Confirm a demo run does not record a collection window.
#    - Show a report-local topic image in the standalone HTML, and omit an
#      external URL, an absolute or escaping path, a missing file and an
#      outside symlink, keeping the topic and report.json unchanged.
#    - Render six stored topics, and fail with exit status 1, leaving the
#      report files as they were, for seven.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt (the command line module imports the whole pipeline)
#
#  Version History:
#  v1.2 2026-11-07
#       Cover omission of a topic image outside its report directory from
#       the standalone HTML, and a render of a report above six topics.
#  v1.1 2026-09-22
#       Identify a demo report by its model field, and stop recording a
#       numeric lookback_hours for one.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import contextlib
import os
import re
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

import cli
from ai_digest import Topic
from ai_digest.render import build
from ai_digest.storage import report_dir, save_report
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
        # 'model' names a live backend here, not "demo": this is an
        # older live report stored before lookback_hours was recorded.
        code, compose = self.render({"model": "claude-legacy"})

        self.assertEqual(0, code)
        self.assertEqual(24, compose.call_args.args[4])

    def test_names_a_demo_report_by_its_model_even_with_a_stale_window(
            self):
        # A demo report stored before this rule existed still carries a
        # numeric lookback_hours. The demo model must still win.
        code, compose = self.render({"model": "demo", "lookback_hours": 72})

        self.assertEqual(0, code)
        self.assertIsNone(compose.call_args.args[4])

    def test_reports_a_missing_date(self):
        with tempfile.TemporaryDirectory() as directory:
            config = replace(Config(), data_dir=directory)
            args = cli.parse_args(["render", "2026-01-01"])
            with self.assertLogs("ai_digest.cli", "ERROR"):
                self.assertEqual(1, cli.command_render(args, config))


def _topic(image=None, title="見出し"):
    return Topic(category="分類", title=title, bullets=["箇条書き。"],
                 sources=[{"title": "t", "url": "https://example.test/"}],
                 image=image)


class StandaloneImageBoundaryTest(unittest.TestCase):
    """ The standalone HTML shows only images inside its own directory. """

    BAD_IMAGES = ("https://evil.test/x.png", "/etc/passwd", "../outside.png",
                  "sub/x.png", "missing.png", "link.png")

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.data = os.path.join(self.temp.name, "data")
        self.outside = os.path.join(self.temp.name, "outside.png")
        with open(self.outside, "wb") as handle:
            handle.write(b"outside bytes")

    def make_report(self, topics):
        save_report(self.data, DATE, topics, {})
        directory = report_dir(self.data, DATE)
        with open(os.path.join(directory, "topic-1.png"), "wb") as handle:
            handle.write(b"local bytes")
        link = os.path.join(directory, "link.png")
        if not os.path.islink(link):
            try:
                os.symlink(self.outside, link)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are not supported here")
        return directory

    def images(self, html):
        return re.findall(r'<img class="thumb" src="([^"]*)"', html)

    def test_a_local_image_is_shown(self):
        directory = self.make_report([_topic("topic-1.png")])

        build.write_report_html(directory, DATE, cli.load_report(
            self.data, DATE)["topics"], {})

        with open(os.path.join(directory, "index.html"),
                  encoding="utf-8") as handle:
            self.assertEqual(["topic-1.png"], self.images(handle.read()))

    def test_every_other_reference_is_omitted_and_the_topic_kept(self):
        for bad in self.BAD_IMAGES:
            with self.subTest(image=bad):
                directory = self.make_report(
                    [_topic("topic-1.png", "良い"), _topic(bad, "悪い")])
                path = os.path.join(directory, "report.json")
                with open(path, "rb") as handle:
                    before = handle.read()
                topics = cli.load_report(self.data, DATE)["topics"]

                build.write_report_html(directory, DATE, topics, {})

                with open(os.path.join(directory, "index.html"),
                          encoding="utf-8") as handle:
                    html = handle.read()
                self.assertEqual(["topic-1.png"], self.images(html))
                self.assertIn("悪い", html)
                with open(path, "rb") as handle:
                    self.assertEqual(before, handle.read())
                self.assertEqual(bad, topics[1].image)


class StoredTopicLimitRenderTest(unittest.TestCase):
    """ A stored report above six topics is refused, never truncated. """

    def render(self, count):
        topics = [_topic(title="見出し{0}".format(i)) for i in range(count)]
        with tempfile.TemporaryDirectory() as data:
            save_report(data, DATE, topics, {})
            directory = report_dir(data, DATE)
            with open(os.path.join(directory, "summary.png"), "wb") as h:
                h.write(b"old image")
            with open(os.path.join(directory, "index.html"), "w") as h:
                h.write("old html")
            snapshot = {}
            for name in sorted(os.listdir(directory)):
                with open(os.path.join(directory, name), "rb") as handle:
                    snapshot[name] = handle.read()
            config = replace(Config(), data_dir=data)
            args = cli.parse_args(["render", DATE])
            with mock.patch.object(cli.compose_image, "compose") as compose:
                with mock.patch.object(cli.build, "write_report_html"):
                    expected = (self.assertLogs("ai_digest.cli", "ERROR")
                                if count > 6 else contextlib.nullcontext())
                    with expected:
                        code = cli.command_render(args, config)
            after = {}
            for name in sorted(os.listdir(directory)):
                with open(os.path.join(directory, name), "rb") as handle:
                    after[name] = handle.read()
        return code, compose, snapshot, after

    def test_six_topics_render(self):
        code, compose, _before, _after = self.render(6)

        self.assertEqual(0, code)
        compose.assert_called_once()

    def test_seven_topics_fail_and_leave_the_files_alone(self):
        code, compose, before, after = self.render(7)

        self.assertEqual(1, code)
        compose.assert_not_called()
        self.assertEqual(before, after)


class RecordedWindowTest(unittest.TestCase):
    """ A run has to store the window before render can read it. """

    def test_demo_does_not_record_a_collection_window(self):
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

        self.assertEqual("demo", stored["stats"]["model"])
        self.assertNotIn("lookback_hours", stored["stats"])


if __name__ == "__main__":
    unittest.main()
