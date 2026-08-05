#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_request_timeout.py: Tests for the SUMMARIZER_TIMEOUT setting
#
#  Description:
#  This test suite follows the summarization timeout from the
#  environment to the SDK, on both API backends and through the command
#  line option. The point of every case is that no caller can reach an
#  endpoint without a bound: summarize() passes the constant rather than
#  None when it is given nothing, so an unattended run cannot hang until
#  the next one starts.
#
#  A timeout that is not positive is refused, since the SDK would refuse
#  it only after the whole collection has been spent, or fall back on a
#  default measured in minutes. A value that cannot be read as a number
#  leaves the default in place.
#
#  The last configuration case keeps the setting apart from HTTP_TIMEOUT
#  on purpose. The two measure different things: a feed answers in
#  moments, while an answer is written from end to end before the client
#  sees any of it.
#
#  No request is made. The API clients are replaced by stubs, so the
#  suite needs no credential and no network.
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
#      python -m unittest tests.test_request_timeout
#
#  Test Cases:
#    - Default to the constant the summarizer defines.
#    - Read SUMMARIZER_TIMEOUT from the environment.
#    - Reject a timeout of zero, and a negative one.
#    - Keep the default on a value that is not a number.
#    - Keep the setting independent of the collector timeout.
#    - Carry the timeout to the Anthropic SDK, and keep its default on None.
#    - Pass the timeout through summarize() on the Anthropic backend.
#    - Bound an Anthropic request by default rather than passing None.
#    - Carry the timeout to the OpenAI SDK, and keep its default on None.
#    - Pass the timeout through summarize() on the OpenAI backend.
#    - Bound an OpenAI compatible request by default.
#    - Replace the setting with the --summarizer-timeout option.
#    - Refuse a --summarizer-timeout that is not positive.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt (the option case imports the command line module)
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

import config
from ai_digest import Entry
from ai_digest.analyzer import openai_compat, summarizer


def _entry():
    return Entry(source_type="news", title="T",
                 url="https://example.test/a", summary="S.",
                 published="2026-08-02T00:00:00+00:00", origin="F")


class ConfigurationTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults_to_the_summarizer_constant(self):
        loaded = self.load({})

        loaded.validate_summarizer_timeout()
        self.assertEqual(summarizer.DEFAULT_TIMEOUT,
                         loaded.summarizer_timeout)

    def test_reads_the_environment(self):
        loaded = self.load({"SUMMARIZER_TIMEOUT": "300"})

        loaded.validate_summarizer_timeout()
        self.assertEqual(300, loaded.summarizer_timeout)

    def test_rejects_zero(self):
        # A timeout of zero would be refused by the SDK only after the
        # whole collection has been spent, or fall back on a default
        # measured in minutes.
        loaded = self.load({"SUMMARIZER_TIMEOUT": "0"})

        with self.assertRaisesRegex(RuntimeError, "positive"):
            loaded.validate_summarizer_timeout()

    def test_rejects_a_negative_timeout(self):
        loaded = self.load({"SUMMARIZER_TIMEOUT": "-30"})

        with self.assertRaisesRegex(RuntimeError, "positive"):
            loaded.validate_summarizer_timeout()

    def test_keeps_the_default_on_an_unparsable_value(self):
        loaded = self.load({"SUMMARIZER_TIMEOUT": "soon"})

        loaded.validate_summarizer_timeout()
        self.assertEqual(summarizer.DEFAULT_TIMEOUT,
                         loaded.summarizer_timeout)

    def test_is_independent_of_the_collector_timeout(self):
        # The two measure different things: a feed answers in moments,
        # while an answer is written from end to end before the client
        # sees any of it.
        loaded = self.load({"HTTP_TIMEOUT": "60"})

        self.assertEqual(60, loaded.http_timeout)
        self.assertEqual(summarizer.DEFAULT_TIMEOUT,
                         loaded.summarizer_timeout)


class AnthropicClientTest(unittest.TestCase):

    def build(self, timeout):
        constructor = mock.Mock(return_value=object())
        module = types.SimpleNamespace(Anthropic=constructor)
        with mock.patch.dict(sys.modules, {"anthropic": module}):
            summarizer._build_client("key", None, None, None, timeout)
        return constructor

    def test_timeout_reaches_the_sdk(self):
        self.build(180).assert_called_once_with(api_key="key", timeout=180)

    def test_none_keeps_the_sdk_default(self):
        self.build(None).assert_called_once_with(api_key="key")

    def test_summarize_passes_the_timeout_through(self):
        client = mock.Mock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="build_report",
                                     input={"topics": []})],
            stop_reason="tool_use", usage=None, id="m-1", model="m")
        with mock.patch.object(summarizer, "_build_client",
                               return_value=client) as builder:
            summarizer.summarize([_entry()], api_key="k", model="m",
                                 max_topics=6, timeout=300)

        self.assertEqual(300, builder.call_args.args[4])

    def test_summarize_bounds_the_request_by_default(self):
        # No caller should be able to reach the endpoint without a
        # timeout, so the default is the constant rather than None.
        client = mock.Mock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="build_report",
                                     input={"topics": []})],
            stop_reason="tool_use", usage=None, id="m-1", model="m")
        with mock.patch.object(summarizer, "_build_client",
                               return_value=client) as builder:
            summarizer.summarize([_entry()], api_key="k", model="m",
                                 max_topics=6)

        self.assertEqual(summarizer.DEFAULT_TIMEOUT,
                         builder.call_args.args[4])


class OpenAiClientTest(unittest.TestCase):

    def build(self, timeout):
        constructor = mock.Mock(return_value=object())
        module = types.SimpleNamespace(OpenAI=constructor)
        with mock.patch.dict(sys.modules, {"openai": module}):
            openai_compat._build_client("key", None, None, timeout)
        return constructor

    def test_timeout_reaches_the_sdk(self):
        self.build(180).assert_called_once_with(api_key="key", timeout=180)

    def test_none_keeps_the_sdk_default(self):
        self.build(None).assert_called_once_with(api_key="key")

    def test_summarize_passes_the_timeout_through(self):
        client = mock.Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            id="r-1", model="m", usage=None,
            choices=[SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(tool_calls=[SimpleNamespace(
                    function=SimpleNamespace(
                        name="build_report",
                        arguments='{"topics": []}'))]))])
        with mock.patch.object(openai_compat, "_build_client",
                               return_value=client) as builder:
            openai_compat.summarize([_entry()], api_key="k", model="m",
                                    max_topics=6, timeout=300)

        self.assertEqual(300, builder.call_args.args[3])

    def test_summarize_bounds_the_request_by_default(self):
        client = mock.Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            id="r-1", model="m", usage=None,
            choices=[SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(tool_calls=[SimpleNamespace(
                    function=SimpleNamespace(
                        name="build_report",
                        arguments='{"topics": []}'))]))])
        with mock.patch.object(openai_compat, "_build_client",
                               return_value=client) as builder:
            openai_compat.summarize([_entry()], api_key="k", model="m",
                                    max_topics=6)

        self.assertEqual(summarizer.DEFAULT_TIMEOUT,
                         builder.call_args.args[3])


class CommandLineTest(unittest.TestCase):

    def test_option_replaces_the_setting(self):
        import cli

        args = cli.parse_args(["run", "--summarizer-timeout", "300"])
        replaced = cli.apply_overrides(config.Config(), args)

        self.assertEqual(300, replaced.summarizer_timeout)

    def test_option_refuses_a_non_positive_value(self):
        import cli

        with self.assertRaises(SystemExit) as raised:
            cli.parse_args(["run", "--summarizer-timeout", "0"])

        self.assertEqual(2, raised.exception.code)


if __name__ == "__main__":
    unittest.main()
