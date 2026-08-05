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
#    - Accept a known summarizer backend, and reject an unknown one.
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

import contextlib
import io
import os
import unittest
from dataclasses import replace

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
