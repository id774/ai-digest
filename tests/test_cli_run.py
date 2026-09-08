#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_cli_run.py: Tests for the preflight of cli.py's 'run' command
#
#  Description:
#  This test suite covers the semantic configuration checks command_run()
#  runs before collect_entries() is ever called. The case that matters is
#  the openai-compatible backend with no explicit SUMMARIZER_BASE_URL: it
#  used to reach the OpenAI SDK unset, letting the SDK's own default
#  endpoint decide where the request went, and now it must fail with exit
#  status 1 before a single source is read.
#
#  Each case proves both halves of the contract: the exit status the
#  failing configuration returns, and that collect_entries() was not
#  called for it. A configuration carrying an explicit base URL, set
#  either directly on the Config or through --summarizer-base-url, is
#  checked the other way, proving that preflight lets it reach
#  collect_entries() rather than failing on the same check.
#
#  The NEWS_FEED_URLS cases cover the same shape of check for the
#  effective, post-override feed list: an invalid one fails before
#  collecting regardless of backend, and a valid --news-feed-urls
#  override still reaches collect_entries() despite an invalid
#  lower-priority raw value underneath it.
#
#  No network is used and no source is read: collect_entries() is
#  replaced by a stub for every case.
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
#      python -m unittest tests.test_cli_run
#
#  Test Cases:
#    - Fail with exit status 1 on a missing base URL, before collecting.
#    - Fail with exit status 1 on an empty base URL, before collecting.
#    - Fail with exit status 1 on a whitespace-only base URL, before
#      collecting.
#    - Reach collect_entries() when the Config already carries an
#      explicit base URL.
#    - Reach collect_entries() when --summarizer-base-url supplies the
#      explicit base URL that the Config lacks.
#    - Leave the anthropic-compatible and plain backends unaffected by
#      the same preflight check.
#    - Never reach collect_entries() for an impossible --date, rejected
#      by main() before command_run() runs.
#    - Fail with exit status 1 on an invalid effective NEWS_FEED_URLS,
#      before collecting.
#    - Reach collect_entries() when a valid --news-feed-urls override
#      replaces an invalid lower-priority raw value.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (collect_entries() is stubbed, never called)
#
#  Version History:
#  v1.1 2026-09-08
#       Cover HTTPS feed preflight and effective CLI override validation.
#  v1.0 2026-09-05
#       Initial release.
#
########################################################################

import unittest
from unittest import mock

import cli
from ai_digest import CollectionResult
from config import Config


class OpenAiCompatibleBaseUrlPreflightTest(unittest.TestCase):

    def run_with(self, base_url):
        config = Config(summarizer_backend="openai-compatible",
                        summarizer_api_key="key", summarizer_model="m",
                        summarizer_base_url=base_url)
        args = cli.parse_args(["run"])
        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            status = cli.command_run(args, config)
        return status, collect

    def test_missing_base_url_fails_before_collecting(self):
        status, collect = self.run_with(None)

        self.assertEqual(1, status)
        collect.assert_not_called()

    def test_empty_base_url_fails_before_collecting(self):
        status, collect = self.run_with("")

        self.assertEqual(1, status)
        collect.assert_not_called()

    def test_whitespace_only_base_url_fails_before_collecting(self):
        status, collect = self.run_with("   ")

        self.assertEqual(1, status)
        collect.assert_not_called()

    def test_configured_base_url_reaches_collection(self):
        _status, collect = self.run_with("https://api.example.test/v1")

        collect.assert_called_once()

    def test_command_line_override_reaches_collection(self):
        config = Config(summarizer_backend="openai-compatible",
                        summarizer_api_key="key", summarizer_model="m",
                        summarizer_base_url=None)
        args = cli.parse_args(["run", "--summarizer-base-url",
                              "https://api.example.test/v1"])
        applied = cli.apply_overrides(config, args)
        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            cli.command_run(args, applied)

        collect.assert_called_once()


class ExplicitDateEarlyRejectionTest(unittest.TestCase):
    """ An impossible --date must never reach collect_entries(). """

    def test_impossible_date_never_reaches_collection(self):
        # The rejection happens inside parse_args(), called by main()
        # before configuration is loaded or command_run() runs, so this
        # goes through main() rather than command_run() directly.
        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            with self.assertRaises(SystemExit) as raised:
                cli.main(["run", "--date", "2026-02-31"])

        self.assertEqual(2, raised.exception.code)
        collect.assert_not_called()


class OtherBackendPreflightTest(unittest.TestCase):
    """ The base URL check must not reach past the openai-compatible backend. """

    def test_anthropic_compatible_with_no_base_url_reaches_collection(self):
        config = Config(summarizer_backend="anthropic-compatible",
                        summarizer_api_key="key", summarizer_base_url=None)
        args = cli.parse_args(["run"])
        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            cli.command_run(args, config)

        collect.assert_called_once()

    def test_plain_with_no_base_url_reaches_collection(self):
        config = Config(summarizer_backend="plain", summarizer_base_url=None)
        args = cli.parse_args(["run"])
        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            cli.command_run(args, config)

        collect.assert_called_once()


class NewsFeedUrlsPreflightTest(unittest.TestCase):
    """
    An invalid effective NEWS_FEED_URLS must fail command_run() before
    collect_entries() is ever called, and a valid --news-feed-urls
    override must let a lower-priority invalid raw value through to
    collection for that one invocation.
    """

    def test_an_invalid_effective_value_fails_before_collecting(self):
        config = Config(summarizer_backend="plain",
                        news_feed_urls=["http://example.test/feed"])
        args = cli.parse_args(["run"])

        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            status = cli.command_run(args, config)

        self.assertEqual(1, status)
        collect.assert_not_called()

    def test_a_valid_override_reaches_collection_despite_the_invalid_base(self):
        config = Config(summarizer_backend="plain",
                        news_feed_urls=["http://old.example/feed"])
        args = cli.parse_args(
            ["run", "--news-feed-urls", "https://new.example/feed"])
        applied = cli.apply_overrides(config, args)

        self.assertEqual(["https://new.example/feed"],
                         applied.news_feed_urls)
        with mock.patch.object(cli, "collect_entries",
                              return_value=CollectionResult()) as collect:
            cli.command_run(args, applied)

        collect.assert_called_once()


if __name__ == "__main__":
    unittest.main()
