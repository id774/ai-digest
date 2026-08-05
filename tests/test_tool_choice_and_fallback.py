#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

import config
from ai_digest.analyzer import summarizer


def _text(text):
    return SimpleNamespace(type="text", text=text)


def _tool_use(name="build_report", tool_input=None):
    return SimpleNamespace(type="tool_use", name=name,
                           input=tool_input if tool_input is not None
                           else {"topics": []})


def _message(blocks, stop_reason="end_turn"):
    return SimpleNamespace(content=blocks, stop_reason=stop_reason)


class ToolChoiceRequestTest(unittest.TestCase):

    def request(self, mode):
        return summarizer._build_request([], "model", 6, "default", mode)

    def test_forced_names_the_tool(self):
        self.assertEqual({"type": "tool", "name": "build_report"},
                         self.request("forced")["tool_choice"])

    def test_any_demands_a_tool_without_naming_it(self):
        # build_report is the only tool offered, so 'any' reaches the
        # same place for an endpoint that drops a named tool_choice.
        self.assertEqual({"type": "any"}, self.request("any")["tool_choice"])

    def test_auto_leaves_the_choice_to_the_model(self):
        self.assertEqual(
            {"type": "auto", "disable_parallel_tool_use": True},
            self.request("auto")["tool_choice"])

    def test_any_is_a_configured_mode(self):
        self.assertIn("any", config.SUMMARIZER_TOOL_CHOICE_MODES)


class TextJsonFallbackTest(unittest.TestCase):

    def extract(self, blocks, enabled, stop_reason="end_turn"):
        return summarizer._extract_tool_input(
            _message(blocks, stop_reason), text_json_fallback=enabled)

    def test_disabled_by_default(self):
        with self.assertRaisesRegex(RuntimeError, "no build_report"):
            self.extract([_text('{"topics": [{"title": "a"}]}')], False)

    def test_reads_a_json_text_block_when_enabled(self):
        with self.assertLogs(summarizer.logger, "WARNING") as logged:
            payload = self.extract([_text('{"topics": [{"title": "a"}]}')],
                                   True)

        self.assertEqual([{"title": "a"}], payload["topics"])
        self.assertIn("SUMMARIZER_TEXT_JSON_FALLBACK", logged.output[0])

    def test_unwraps_a_fenced_block(self):
        with self.assertLogs(summarizer.logger, "WARNING"):
            payload = self.extract(
                [_text('```json\n{"topics": [{"title": "a"}]}\n```')], True)

        self.assertEqual([{"title": "a"}], payload["topics"])

    def test_ignores_prose(self):
        # The guard that makes this path safe: text without a topics
        # list is not a report, however JSON-ish it looks.
        with self.assertRaisesRegex(RuntimeError, "no build_report"):
            self.extract([_text("すみません、ツールを使えませんでした。")], True)

    def test_ignores_json_without_a_topics_list(self):
        with self.assertRaisesRegex(RuntimeError, "no build_report"):
            self.extract([_text('{"error": "unsupported"}')], True)

    def test_ignores_a_topics_key_that_is_not_a_list(self):
        with self.assertRaisesRegex(RuntimeError, "no build_report"):
            self.extract([_text('{"topics": "none"}')], True)

    def test_a_real_tool_call_still_wins(self):
        payload = self.extract(
            [_text('{"topics": [{"title": "text"}]}'),
             _tool_use(tool_input={"topics": [{"title": "tool"}]})], True)

        self.assertEqual([{"title": "tool"}], payload["topics"])

    def test_truncated_answer_is_still_reported_as_truncated(self):
        with self.assertRaisesRegex(RuntimeError, "max_tokens"):
            self.extract([_tool_use()], True, stop_reason="max_tokens")


class MaxRetriesTest(unittest.TestCase):

    def build(self, max_retries):
        constructor = mock.Mock(return_value=object())
        module = types.SimpleNamespace(Anthropic=constructor)
        with mock.patch.dict(sys.modules, {"anthropic": module}):
            summarizer._build_client("key", None, None, max_retries)
        return constructor

    def test_zero_is_passed_through(self):
        # One request per run is the point: the SDK otherwise retries
        # on its own and two runs are no longer one request each.
        self.build(0).assert_called_once_with(api_key="key", max_retries=0)

    def test_none_keeps_the_sdk_default(self):
        self.build(None).assert_called_once_with(api_key="key")


class ConfigurationTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults(self):
        loaded = self.load({})

        loaded.validate_protocol_options()
        self.assertEqual("disabled", loaded.summarizer_text_json_fallback)
        self.assertEqual(2, loaded.summarizer_max_retries)

    def test_accepts_any_as_a_tool_choice(self):
        loaded = self.load({"SUMMARIZER_TOOL_CHOICE_MODE": "any"})

        loaded.validate_protocol_options()
        self.assertEqual("any", loaded.summarizer_tool_choice_mode)

    def test_rejects_an_unknown_fallback_value(self):
        loaded = self.load({"SUMMARIZER_TEXT_JSON_FALLBACK": "yes"})

        with self.assertRaisesRegex(RuntimeError, "expected one of"):
            loaded.validate_protocol_options()

    def test_rejects_negative_retries(self):
        loaded = self.load({"SUMMARIZER_MAX_RETRIES": "-1"})

        with self.assertRaisesRegex(RuntimeError, "zero or more"):
            loaded.validate_retry_budget()

    def test_openai_backend_needs_a_credential(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible"})

        loaded.validate_summarizer_backend()
        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_API_KEY"):
            loaded.validate_summarizer_auth()

    def test_openai_backend_needs_a_model(self):
        # The anthropic-compatible backend falls back on a known Claude
        # model here; this one has nothing to fall back on, because the
        # models an endpoint offers are its own.
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible",
                            "SUMMARIZER_API_KEY": "key"})

        loaded.validate_summarizer_auth()
        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_MODEL"):
            loaded.validate_summarizer_model()

    def test_openai_backend_configured(self):
        loaded = self.load({
            "SUMMARIZER_BACKEND": "openai-compatible",
            "SUMMARIZER_API_KEY": "key",
            "SUMMARIZER_MODEL": "preview/Kimi-K2.6",
            "SUMMARIZER_BASE_URL": "https://api.ai.sakura.ad.jp/v1",
        })

        loaded.validate_summarizer_backend()
        loaded.validate_summarizer_auth()
        loaded.validate_summarizer_model()
        self.assertEqual("https://api.ai.sakura.ad.jp/v1",
                         loaded.summarizer_base_url)
        self.assertEqual("preview/Kimi-K2.6", loaded.resolved_model)

    def test_openai_backend_accepts_a_bearer_token(self):
        # The OpenAI SDK sends its api_key as a Bearer token, so the
        # two spellings of the credential describe one request.
        loaded = self.load({
            "SUMMARIZER_BACKEND": "openai-compatible",
            "SUMMARIZER_AUTH_TOKEN": "uuid:secret",
            "SUMMARIZER_MODEL": "preview/Kimi-K2.6",
        })

        loaded.validate_summarizer_auth()
        loaded.validate_summarizer_model()


if __name__ == "__main__":
    unittest.main()
