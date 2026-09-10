#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_report_publication.py: Publication failure atomicity of cli.py
#
#  Description:
#  This test suite covers the writer paths of cli.py end to end: 'run',
#  'demo' and 'render' all build a report in a staging directory and
#  publish it to <DATA_DIR>/<date> only once every artifact it needs
#  exists, so a failure partway through must never leave a half-written
#  or mixed-version report where a complete one used to stand, or should
#  now stand.
#
#  Each case injects a failure into one stage of the pipeline -
#  illustration, the JSON write, the summary image, the standalone HTML,
#  or the final publish itself - and checks the archive from the
#  outside, through list_dates() and load_report(), exactly as the
#  viewer would. 'run' uses SUMMARIZER_BACKEND=plain and collect_entries()
#  is replaced by a stub, so no network access and no credential are
#  needed; every case uses a temporary directory as the archive and
#  touches nothing under data/.
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
#      python -m unittest tests.test_report_publication
#
#  Test Cases:
#    - 'run' on a new date: a failure in illustration, in the JSON write,
#      in the summary image, in the standalone HTML, or in the final
#      publish itself leaves no final report and exits 1.
#    - 'run' on an existing date: the same failures leave the existing
#      report exactly as it was and exit 1.
#    - 'run' on an existing date: a successful rerun replaces the report
#      as a whole and drops an artifact only the previous report had.
#    - 'demo' follows the same new-date and same-date publication
#      contract as 'run', for one generation failure, one publication
#      failure and a successful replacement.
#    - 'demo' rejects an impossible sample date before any report work,
#      when '--date' does not override it.
#    - 'render' on a generation failure leaves the stored report
#      untouched; on a publication failure it rolls the stored report
#      back; on success it keeps the authoritative report.json and topic
#      assets while replacing the derived artifacts.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt (the command line module imports the whole pipeline)
#
#  Version History:
#  v1.0 2026-09-06
#       Initial release.
#
########################################################################

import io
import json
import os
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

from PIL import Image

import cli
from ai_digest import CollectionResult, Entry, Topic
from ai_digest.storage import (BACKUP_PREFIX, list_dates, load_report,
                               report_dir, save_report)
from config import Config

DATE = "2026-08-02"


def tiny_png_bytes() -> bytes:
    """ Return a minimal, decodable one pixel PNG for a topic image. """
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), "red").save(buffer, format="PNG")
    return buffer.getvalue()


def make_entries():
    """ Return two distinct entries, recent enough to survive dedup. """
    return [
        Entry(source_type="paper", title="Paper about A",
             url="https://example.test/a",
             summary="One sentence about A. Another sentence.",
             published="2026-08-02T00:00:00+00:00", origin="cs.AI"),
        Entry(source_type="news", title="News about B",
             url="https://example.test/b",
             summary="One sentence about B.",
             published="2026-08-02T01:00:00+00:00", origin="Example Feed"),
    ]


def make_topic(marker: str = "old") -> Topic:
    """ Return a minimal topic usable as a stored report's content. """
    return Topic(category="テスト", title="見出し", bullets=[marker],
                sources=[{"title": "出典", "url": "https://example.test/a"}])


def make_config(data_dir: str, **overrides) -> Config:
    """ Return a config that never touches the network or a credential. """
    return replace(Config(), data_dir=data_dir, summarizer_backend="plain",
                   **overrides)


def run_with_stub_collection(argv, config):
    """ Run cli.command_run with collect_entries() replaced by a stub. """
    args = cli.parse_args(argv)
    result = CollectionResult(entries=make_entries(), sources_total=2)
    with mock.patch.object(cli, "collect_entries", return_value=result):
        return cli.command_run(args, config)


# The failure is injected on the object cli.py itself calls, so a case
# proves the boundary command_run() and command_demo() actually use.
GENERATION_FAILURE_TARGETS = (
    "cli.attach_images",
    "cli.write_report_json",
    "cli.compose_image.compose",
    "cli.build.write_report_html",
)


class RunNewDateTest(unittest.TestCase):
    """ 'run' filing a date that has no report yet. """

    def test_a_generation_failure_leaves_no_final_report(self):
        for target in GENERATION_FAILURE_TARGETS:
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as data_dir:
                    config = make_config(data_dir)
                    with mock.patch(target, side_effect=RuntimeError("boom")):
                        with self.assertLogs("ai_digest.cli", "ERROR"):
                            status = run_with_stub_collection(
                                ["run", "--date", DATE, "--no-images"],
                                config)

                    self.assertEqual(1, status)
                    self.assertEqual([], list_dates(data_dir))
                    self.assertFalse(os.path.isdir(
                        report_dir(data_dir, DATE)))

    def test_a_publication_failure_leaves_no_final_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            config = make_config(data_dir)
            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=OSError("simulated disk failure")):
                with self.assertLogs("ai_digest.cli", "ERROR"):
                    status = run_with_stub_collection(
                        ["run", "--date", DATE, "--no-images"], config)

            self.assertEqual(1, status)
            self.assertEqual([], list_dates(data_dir))
            self.assertFalse(os.path.isdir(report_dir(data_dir, DATE)))

    def test_success_publishes_a_complete_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            config = make_config(data_dir)
            status = run_with_stub_collection(
                ["run", "--date", DATE, "--no-images"], config)

            self.assertEqual(0, status)
            self.assertEqual([DATE], list_dates(data_dir))
            loaded = load_report(data_dir, DATE)
            self.assertTrue(loaded["topics"])
            directory = report_dir(data_dir, DATE)
            self.assertTrue(os.path.isfile(
                os.path.join(directory, "summary.png")))
            self.assertTrue(os.path.isfile(
                os.path.join(directory, "index.html")))


class RunSameDateTest(unittest.TestCase):
    """ 'run' filing a date that already holds a complete report. """

    def seed_existing_report(self, data_dir):
        save_report(data_dir, DATE, [make_topic("old")], {"run": "old"})
        # A name the new report's two topics never produce, so its
        # survival can only mean the old report's directory was not
        # replaced as a whole.
        stale_path = os.path.join(report_dir(data_dir, DATE), "topic-9.png")
        with open(stale_path, "wb") as handle:
            handle.write(b"stale image data")
        return stale_path

    def test_a_generation_failure_keeps_the_existing_report(self):
        for target in GENERATION_FAILURE_TARGETS:
            with self.subTest(target=target):
                with tempfile.TemporaryDirectory() as data_dir:
                    self.seed_existing_report(data_dir)
                    config = make_config(data_dir)
                    with mock.patch(target, side_effect=RuntimeError("boom")):
                        with self.assertLogs("ai_digest.cli", "ERROR"):
                            status = run_with_stub_collection(
                                ["run", "--date", DATE, "--no-images"],
                                config)

                    self.assertEqual(1, status)
                    loaded = load_report(data_dir, DATE)
                    self.assertEqual({"run": "old"}, loaded["stats"])
                    self.assertEqual("old", loaded["topics"][0].bullets[0])

    def test_a_publication_failure_keeps_the_existing_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            self.seed_existing_report(data_dir)
            config = make_config(data_dir)
            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=OSError("simulated disk failure")):
                with self.assertLogs("ai_digest.cli", "ERROR"):
                    status = run_with_stub_collection(
                        ["run", "--date", DATE, "--no-images"], config)

            self.assertEqual(1, status)
            loaded = load_report(data_dir, DATE)
            self.assertEqual({"run": "old"}, loaded["stats"])

    def test_success_replaces_the_report_and_drops_stale_artifacts(self):
        with tempfile.TemporaryDirectory() as data_dir:
            stale_path = self.seed_existing_report(data_dir)
            config = make_config(data_dir)

            status = run_with_stub_collection(
                ["run", "--date", DATE, "--no-images"], config)

            self.assertEqual(0, status)
            self.assertFalse(os.path.isfile(stale_path))
            loaded = load_report(data_dir, DATE)
            self.assertNotEqual({"run": "old"}, loaded["stats"])
            self.assertEqual([DATE], list_dates(data_dir))
            leftover = [name for name in os.listdir(data_dir)
                       if name.startswith(BACKUP_PREFIX)]
            self.assertEqual([], leftover)


class DemoPublicationTest(unittest.TestCase):
    """ 'demo' follows the same publication contract as 'run'. """

    def demo_config(self, data_dir):
        return make_config(data_dir, max_topics=2)

    def test_a_generation_failure_leaves_no_final_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            config = self.demo_config(data_dir)
            args = cli.parse_args(["demo", "--date", DATE])
            with mock.patch("cli.compose_image.compose",
                            side_effect=RuntimeError("boom")):
                with self.assertLogs("ai_digest.cli", "ERROR"):
                    status = cli.command_demo(args, config)

            self.assertEqual(1, status)
            self.assertEqual([], list_dates(data_dir))

    def test_a_publication_failure_keeps_the_existing_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            save_report(data_dir, DATE, [make_topic("old")], {"run": "old"})
            config = self.demo_config(data_dir)
            args = cli.parse_args(["demo", "--date", DATE])
            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=OSError("simulated disk failure")):
                with self.assertLogs("ai_digest.cli", "ERROR"):
                    status = cli.command_demo(args, config)

            self.assertEqual(1, status)
            loaded = load_report(data_dir, DATE)
            self.assertEqual({"run": "old"}, loaded["stats"])

    def test_success_replaces_an_existing_report(self):
        with tempfile.TemporaryDirectory() as data_dir:
            stale_path = os.path.join(report_dir(data_dir, DATE), "stale.png")
            save_report(data_dir, DATE, [make_topic("old")], {"run": "old"})
            os.makedirs(os.path.dirname(stale_path), exist_ok=True)
            with open(stale_path, "wb") as handle:
                handle.write(b"stale")
            config = self.demo_config(data_dir)
            args = cli.parse_args(["demo", "--date", DATE])

            status = cli.command_demo(args, config)

            self.assertEqual(0, status)
            self.assertFalse(os.path.isfile(stale_path))
            loaded = load_report(data_dir, DATE)
            self.assertNotEqual({"run": "old"}, loaded["stats"])

    def test_an_impossible_sample_date_stops_before_any_report_work(self):
        # '--date' is not given, so command_demo() falls back on the
        # sample's own date, which this custom sample makes impossible.
        sample = {
            "date": "2026-02-31",
            "entries": [{
                "source_type": "paper",
                "title": "A paper",
                "url": "https://example.test/paper",
            }],
            "build_report": {"topics": [{
                "category": "テスト",
                "title": "見出し",
                "bullets": ["箇条書き。"],
                "source_indexes": [0],
            }]},
        }
        with tempfile.TemporaryDirectory() as data_dir:
            sample_path = os.path.join(data_dir, "sample.json")
            with open(sample_path, "w", encoding="utf-8") as handle:
                json.dump(sample, handle)
            config = self.demo_config(data_dir)
            args = cli.parse_args(["demo", "--input", sample_path])

            with mock.patch("cli.compose_image.compose") as compose:
                with mock.patch("cli.build.write_report_html") as write_html:
                    with self.assertLogs("ai_digest.cli", "ERROR"):
                        status = cli.command_demo(args, config)

            self.assertEqual(1, status)
            self.assertEqual([], list_dates(data_dir))
            compose.assert_not_called()
            write_html.assert_not_called()


class RenderPublicationTest(unittest.TestCase):
    """ 'render' rebuilding the derived artifacts of a stored report. """

    def seed_existing_report(self, data_dir):
        topic = make_topic("authoritative")
        save_report(data_dir, DATE, [topic], {"lookback_hours": 48})
        image_path = os.path.join(report_dir(data_dir, DATE), "topic-1.png")
        with open(image_path, "wb") as handle:
            handle.write(tiny_png_bytes())
        topic.image = "topic-1.png"
        save_report(data_dir, DATE, [topic], {"lookback_hours": 48})
        return image_path

    def test_a_generation_failure_leaves_the_report_untouched(self):
        with tempfile.TemporaryDirectory() as data_dir:
            image_path = self.seed_existing_report(data_dir)
            before = load_report(data_dir, DATE)
            config = make_config(data_dir)
            args = cli.parse_args(["render", DATE])

            with mock.patch("cli.build.write_report_html",
                            side_effect=RuntimeError("boom")):
                with self.assertLogs("ai_digest.cli", "ERROR"):
                    status = cli.command_render(args, config)

            self.assertEqual(1, status)
            after = load_report(data_dir, DATE)
            self.assertEqual(before["stats"], after["stats"])
            self.assertEqual("authoritative", after["topics"][0].bullets[0])
            with open(image_path, "rb") as handle:
                self.assertEqual(tiny_png_bytes(), handle.read())

    def test_a_publication_failure_rolls_back(self):
        with tempfile.TemporaryDirectory() as data_dir:
            self.seed_existing_report(data_dir)
            before = load_report(data_dir, DATE)
            config = make_config(data_dir)
            args = cli.parse_args(["render", DATE])

            with mock.patch("ai_digest.storage.os.rename",
                            side_effect=OSError("simulated disk failure")):
                with self.assertLogs("ai_digest.cli", "ERROR"):
                    status = cli.command_render(args, config)

            self.assertEqual(1, status)
            after = load_report(data_dir, DATE)
            self.assertEqual(before["stats"], after["stats"])
            self.assertEqual("authoritative", after["topics"][0].bullets[0])

    def test_success_keeps_authoritative_data_and_updates_derived_artifacts(
            self):
        with tempfile.TemporaryDirectory() as data_dir:
            self.seed_existing_report(data_dir)
            before = load_report(data_dir, DATE)
            config = make_config(data_dir)
            args = cli.parse_args(["render", DATE])
            directory = report_dir(data_dir, DATE)
            old_summary = os.path.join(directory, "summary.png")
            if os.path.isfile(old_summary):
                os.remove(old_summary)

            status = cli.command_render(args, config)

            self.assertEqual(0, status)
            after = load_report(data_dir, DATE)
            self.assertEqual(before["stats"], after["stats"])
            self.assertEqual("authoritative", after["topics"][0].bullets[0])
            self.assertTrue(os.path.isfile(old_summary))
            self.assertTrue(os.path.isfile(
                os.path.join(directory, "index.html")))
            with open(os.path.join(directory, "topic-1.png"), "rb") as handle:
                self.assertEqual(tiny_png_bytes(), handle.read())


if __name__ == "__main__":
    unittest.main()
