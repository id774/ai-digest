#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_output_budget.py: Tests for the MAX_OUTPUT_TOKENS setting
#
#  Description:
#  This test suite follows the output budget from the environment to the
#  request, on both API backends. The setting used to be dropped on the
#  floor, with dotenv putting it in the environment and nothing ever
#  reading it, so the cases below check the configured value at each
#  stage rather than only that a request carries some limit. The value
#  they configure differs from the default on purpose: reading nothing
#  at all must not be able to pass.
#
#  A budget that is not positive is refused, since it would be refused
#  by the SDK only after a whole collection has been spent, while a
#  value that cannot be read as a number leaves the default in place.
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
#      python -m unittest tests.test_output_budget
#
#  Test Cases:
#    - Default to the constant the summarizer defines.
#    - Read MAX_OUTPUT_TOKENS from the environment.
#    - Reject a budget of zero, and a negative one.
#    - Keep the default on a value that is not a number.
#    - Carry the default budget into an Anthropic request.
#    - Carry a configured budget into an Anthropic request.
#    - Pass the budget through summarize() on the Anthropic backend.
#    - Carry the shared default into an OpenAI compatible request.
#    - Carry a configured budget into an OpenAI compatible request.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the API clients are stubbed, never imported)
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import os
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

        loaded.validate_output_budget()
        self.assertEqual(summarizer.MAX_OUTPUT_TOKENS,
                         loaded.max_output_tokens)

    def test_reads_the_environment(self):
        # The setting used to be dropped on the floor: dotenv put it in
        # the environment and nothing ever read it. The value differs
        # from the default on purpose, so that reading nothing at all
        # cannot pass this test.
        loaded = self.load({"MAX_OUTPUT_TOKENS": "12000"})

        loaded.validate_output_budget()
        self.assertEqual(12000, loaded.max_output_tokens)

    def test_rejects_zero(self):
        loaded = self.load({"MAX_OUTPUT_TOKENS": "0"})

        with self.assertRaisesRegex(RuntimeError, "positive"):
            loaded.validate_output_budget()

    def test_rejects_a_negative_budget(self):
        loaded = self.load({"MAX_OUTPUT_TOKENS": "-100"})

        with self.assertRaisesRegex(RuntimeError, "positive"):
            loaded.validate_output_budget()

    def test_keeps_the_default_on_an_unparsable_value(self):
        loaded = self.load({"MAX_OUTPUT_TOKENS": "lots"})

        loaded.validate_output_budget()
        self.assertEqual(summarizer.MAX_OUTPUT_TOKENS,
                         loaded.max_output_tokens)


class AnthropicRequestTest(unittest.TestCase):

    def test_default_budget_reaches_the_request(self):
        request = summarizer._build_request([], "m", 6, "default", "forced")

        self.assertEqual(summarizer.MAX_OUTPUT_TOKENS, request["max_tokens"])

    def test_configured_budget_reaches_the_request(self):
        request = summarizer._build_request([], "m", 6, "default", "forced",
                                            12000)

        self.assertEqual(12000, request["max_tokens"])

    def test_summarize_passes_the_budget_through(self):
        client = mock.Mock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="build_report",
                                     input={"topics": []})],
            stop_reason="tool_use", usage=None, id="m-1", model="m")
        with mock.patch.object(summarizer, "_build_client",
                               return_value=client):
            summarizer.summarize([_entry()], api_key="k", model="m",
                                 max_topics=6, max_output_tokens=12000)

        self.assertEqual(12000,
                         client.messages.create.call_args.kwargs["max_tokens"])


class OpenAiRequestTest(unittest.TestCase):

    def summarize(self, **kwargs):
        client = mock.Mock()
        client.chat.completions.create.return_value = SimpleNamespace(
            id="r-1", model="m", usage=None,
            choices=[SimpleNamespace(
                finish_reason="tool_calls",
                message=SimpleNamespace(tool_calls=[SimpleNamespace(
                    function=SimpleNamespace(name="build_report",
                                             arguments='{"topics": []}'))]))])
        with mock.patch.object(openai_compat, "_build_client",
                               return_value=client):
            openai_compat.summarize([_entry()], api_key="k", model="m",
                                    max_topics=6, **kwargs)
        return client.chat.completions.create.call_args.kwargs

    def test_defaults_to_the_shared_constant(self):
        self.assertEqual(openai_compat.MAX_OUTPUT_TOKENS,
                         self.summarize()["max_tokens"])

    def test_configured_budget_reaches_the_request(self):
        self.assertEqual(12000,
                         self.summarize(max_output_tokens=12000)["max_tokens"])


if __name__ == "__main__":
    unittest.main()
