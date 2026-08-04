#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
        for option in ("--anthropic-api-key", "--anthropic-auth-token",
                       "--openai-api-key"):
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
        args = cli.parse_args(["run", "--anthropic-max-retries", "0"])

        self.assertEqual(0, args.anthropic_max_retries)

    def test_rejects_a_negative_retry_budget(self):
        self.assertRejected(["run", "--anthropic-max-retries", "-1"])


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
