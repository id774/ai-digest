#!/usr/bin/env python
# -*- coding: utf-8 -*-

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
        # the environment and nothing ever read it.
        loaded = self.load({"MAX_OUTPUT_TOKENS": "8000"})

        loaded.validate_output_budget()
        self.assertEqual(8000, loaded.max_output_tokens)

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
        self.assertEqual(4000, loaded.max_output_tokens)


class AnthropicRequestTest(unittest.TestCase):

    def test_default_budget_reaches_the_request(self):
        request = summarizer._build_request([], "m", 6, "default", "forced")

        self.assertEqual(summarizer.MAX_OUTPUT_TOKENS, request["max_tokens"])

    def test_configured_budget_reaches_the_request(self):
        request = summarizer._build_request([], "m", 6, "default", "forced",
                                            8000)

        self.assertEqual(8000, request["max_tokens"])

    def test_summarize_passes_the_budget_through(self):
        client = mock.Mock()
        client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", name="build_report",
                                     input={"topics": []})],
            stop_reason="tool_use", usage=None, id="m-1", model="m")
        with mock.patch.object(summarizer, "_build_client",
                               return_value=client):
            summarizer.summarize([_entry()], api_key="k", model="m",
                                 max_topics=6, max_output_tokens=8000)

        self.assertEqual(8000,
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
        self.assertEqual(8000,
                         self.summarize(max_output_tokens=8000)["max_tokens"])


if __name__ == "__main__":
    unittest.main()
