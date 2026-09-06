#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_cli_options.py: Tests for the option handling of cli.py
#
#  Description:
#  This test suite covers what a command line option is allowed to do to
#  the configuration: replace exactly one setting and leave the rest
#  alone, split a list the way the environment variable of the same name
#  is split, and make a data directory absolute. It also checks that
#  every name in OVERRIDABLE_FIELDS is a real field of Config, so that a
#  renamed setting cannot leave a silently dead option behind.
#
#  A rule of its own is that no credential gets an option, because a
#  command line is readable by every user of the host. The remaining
#  cases pin the values the parser refuses outright, since a number the
#  pipeline cannot use should cost a command line rather than a run.
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
#      python -m unittest tests.test_cli_options
#
#  Test Cases:
#    - Return the configuration unchanged when no option is given.
#    - Replace the window with --lookback-hours and leave the rest alone.
#    - Split a list option the way the environment ones are split.
#    - Make the data directory absolute.
#    - Keep every overridable field a real field of the configuration.
#    - Give no option to a credential.
#    - Reject a window that is not a number, and one of zero.
#    - Accept zero retries, and reject a negative retry budget.
#    - Accept zero on --summarizer-max-retries only, rejecting it on every
#      other numeric option.
#    - Reject a non-integer or a negative value on every numeric option.
#    - Accept a known summarizer backend, and reject an unknown one.
#    - Accept a real calendar date on 'run', 'demo' and 'render', and
#      reject an impossible or a non-canonical one on all three.
#    - Accept a usable --font-path, and reject one that is blank, missing,
#      a directory, or a file Pillow cannot load, on all three subcommands.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt (the command line module imports the whole pipeline)
#
#  Version History:
#  v1.1 2026-09-06
#       Reject impossible report dates and unusable font paths early.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import contextlib
import io
import os
import tempfile
import unittest
from dataclasses import replace
from unittest import mock

import cli
from config import Config


def refused(argv):
    """ Return the exit code argparse used to reject a command line. """
    with contextlib.redirect_stderr(io.StringIO()):
        try:
            cli.parse_args(argv)
        except SystemExit as exit_request:
            return exit_request.code
    raise AssertionError("{0} was accepted".format(argv))


class OverrideTest(unittest.TestCase):
    """ An option must replace one setting and leave the rest alone. """

    def override(self, argv):
        args = cli.parse_args(argv)
        return cli.apply_overrides(Config(), args)

    def test_nothing_given_returns_the_configuration_unchanged(self):
        configured = replace(Config(), lookback_hours=48, max_topics=3)

        applied = cli.apply_overrides(configured, cli.parse_args(["run"]))

        self.assertIs(configured, applied)

    def test_lookback_hours_replaces_the_window(self):
        applied = self.override(["run", "--lookback-hours", "72"])

        self.assertEqual(72, applied.lookback_hours)
        self.assertEqual(Config().max_topics, applied.max_topics)

    def test_lists_are_split_like_the_environment_ones(self):
        applied = self.override(["run", "--arxiv-categories",
                                 "cs.AI, cs.CV ,"])

        self.assertEqual(["cs.AI", "cs.CV"], applied.arxiv_categories)

    def test_data_dir_is_made_absolute(self):
        applied = self.override(["list", "--data-dir", "reports"])

        self.assertEqual(os.path.abspath("reports"), applied.data_dir)

    def test_every_overridable_field_exists_on_the_configuration(self):
        fields = set(vars(Config()))

        self.assertEqual(set(), set(cli.OVERRIDABLE_FIELDS) - fields)

    def test_credentials_have_no_option(self):
        for option in ("--summarizer-api-key", "--summarizer-auth-token"):
            self.assertEqual(2, refused(["run", option, "secret"]))


class NumericOptionTest(unittest.TestCase):
    """ A number the pipeline cannot use must be refused by the parser. """

    def assertRejected(self, argv):
        self.assertEqual(2, refused(argv))

    def test_rejects_a_non_numeric_window(self):
        self.assertRejected(["run", "--lookback-hours", "soon"])

    def test_rejects_a_window_of_zero(self):
        self.assertRejected(["run", "--lookback-hours", "0"])

    def test_accepts_zero_retries(self):
        args = cli.parse_args(["run", "--summarizer-max-retries", "0"])

        self.assertEqual(0, args.summarizer_max_retries)

    def test_rejects_a_negative_retry_budget(self):
        self.assertRejected(["run", "--summarizer-max-retries", "-1"])


# (option, minimum) for every numeric option 'run' accepts. Retries alone
# allows zero; the environment variable of the same name shares this
# minimum, which is what NumericSettingTest in test_config.py pins on
# the other side of the same setting.
NUMERIC_OPTIONS = (
    ("--summarizer-max-retries", 0),
    ("--max-topics", 1),
    ("--lookback-hours", 1),
    ("--arxiv-max-results", 1),
    ("--http-timeout", 1),
    ("--max-output-tokens", 1),
    ("--summarizer-timeout", 1),
)


class NumericOptionParityTest(unittest.TestCase):
    """ Every numeric option shares its minimum with the same setting read from the environment. """

    def dest(self, option):
        return option.lstrip("-").replace("-", "_")

    def test_only_retries_accepts_zero(self):
        for option, minimum in NUMERIC_OPTIONS:
            with self.subTest(option=option):
                if minimum == 0:
                    args = cli.parse_args(["run", option, "0"])
                    self.assertEqual(0, getattr(args, self.dest(option)))
                else:
                    self.assertEqual(2, refused(["run", option, "0"]))

    def test_every_option_rejects_a_non_integer_value(self):
        for option, _minimum in NUMERIC_OPTIONS:
            with self.subTest(option=option):
                self.assertEqual(2, refused(["run", option, "not-a-number"]))

    def test_every_option_rejects_a_negative_value(self):
        for option, _minimum in NUMERIC_OPTIONS:
            with self.subTest(option=option):
                self.assertEqual(2, refused(["run", option, "-1"]))


# A leap day only 2024 actually has, and a shape-valid but impossible
# calendar date, for the three subcommands that take an explicit date.
VALID_DATE = "2024-02-29"
IMPOSSIBLE_DATE = "2026-02-31"
NON_CANONICAL_DATE = "2026-2-1"


class ReportDateOptionTest(unittest.TestCase):
    """ 'run', 'demo' and 'render' reject an impossible date at the parser. """

    def test_run_accepts_a_real_calendar_date(self):
        args = cli.parse_args(["run", "--date", VALID_DATE])

        self.assertEqual(VALID_DATE, args.date)

    def test_demo_accepts_a_real_calendar_date(self):
        args = cli.parse_args(["demo", "--date", VALID_DATE])

        self.assertEqual(VALID_DATE, args.date)

    def test_render_accepts_a_real_calendar_date(self):
        args = cli.parse_args(["render", VALID_DATE])

        self.assertEqual(VALID_DATE, args.date)

    def test_run_rejects_an_impossible_calendar_date(self):
        self.assertEqual(2, refused(["run", "--date", IMPOSSIBLE_DATE]))

    def test_demo_rejects_an_impossible_calendar_date(self):
        self.assertEqual(2, refused(["demo", "--date", IMPOSSIBLE_DATE]))

    def test_render_rejects_an_impossible_calendar_date(self):
        self.assertEqual(2, refused(["render", IMPOSSIBLE_DATE]))

    def test_run_rejects_a_non_canonical_date(self):
        self.assertEqual(2, refused(["run", "--date", NON_CANONICAL_DATE]))

    def test_demo_rejects_a_non_canonical_date(self):
        self.assertEqual(2, refused(["demo", "--date", NON_CANONICAL_DATE]))

    def test_render_rejects_a_non_canonical_date(self):
        self.assertEqual(2, refused(["render", NON_CANONICAL_DATE]))


class FontPathOptionTest(unittest.TestCase):
    """
    'run', 'demo' and 'render' reject an unusable --font-path at the
    parser boundary. is_usable_font_path() is mocked for the usable and
    the Pillow-refused cases, so nothing here depends on a font actually
    installed on the host; the missing-file and directory cases need no
    mock, since they fail the existence check on their own.
    """

    def test_accepts_a_usable_path(self):
        with mock.patch.object(cli, "is_usable_font_path", return_value=True):
            args = cli.parse_args(["run", "--font-path", "/some/font.ttf"])

        self.assertEqual("/some/font.ttf", args.font_path)

    def test_rejects_a_path_pillow_cannot_load(self):
        with mock.patch.object(cli, "is_usable_font_path",
                               return_value=False):
            self.assertEqual(
                2, refused(["run", "--font-path", "/bad/font.ttf"]))

    def test_rejects_a_missing_file(self):
        self.assertEqual(
            2, refused(["run", "--font-path", "/no/such/font.ttf"]))

    def test_rejects_a_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(2, refused(["run", "--font-path", directory]))

    def test_rejects_a_blank_value(self):
        self.assertEqual(2, refused(["run", "--font-path", ""]))

    def test_rejects_a_whitespace_only_value(self):
        self.assertEqual(2, refused(["run", "--font-path", "   "]))

    def test_demo_and_render_reject_the_same_way(self):
        self.assertEqual(2, refused(["demo", "--font-path", ""]))
        self.assertEqual(
            2, refused(["render", "2026-08-02", "--font-path", ""]))


class ModeOptionTest(unittest.TestCase):
    """ Token settings must accept the documented values only. """

    def test_accepts_a_known_backend(self):
        applied = cli.apply_overrides(
            Config(), cli.parse_args(["run", "--summarizer-backend", "plain"]))

        self.assertEqual("plain", applied.summarizer_backend)

    def test_rejects_an_unknown_backend(self):
        self.assertEqual(2, refused(["run", "--summarizer-backend", "claud"]))


if __name__ == "__main__":
    unittest.main()
