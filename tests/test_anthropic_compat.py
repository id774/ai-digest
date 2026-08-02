#!/usr/bin/env python
# -*- coding: utf-8 -*-

import json
import os
import sys
import types
import unittest
from unittest import mock

import config
from ai_digest import Entry
from ai_digest.analyzer import summarizer


class ConfigAuthenticationTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_loads_api_key_authentication(self):
        loaded = self.load({"ANTHROPIC_API_KEY": "key"})

        loaded.validate_anthropic_auth()
        self.assertEqual("key", loaded.anthropic_api_key)
        self.assertIsNone(loaded.anthropic_auth_token)

    def test_loads_bearer_authentication_and_base_url(self):
        loaded = self.load({
            "ANTHROPIC_AUTH_TOKEN": "uuid:secret",
            "ANTHROPIC_BASE_URL": "https://api.example.test",
        })

        loaded.validate_anthropic_auth()
        self.assertEqual("uuid:secret", loaded.anthropic_auth_token)
        self.assertEqual("https://api.example.test", loaded.anthropic_base_url)

    def test_rejects_multiple_authentication_values(self):
        loaded = self.load({
            "ANTHROPIC_API_KEY": "key",
            "ANTHROPIC_AUTH_TOKEN": "token",
        })

        with self.assertRaisesRegex(RuntimeError, "only one"):
            loaded.validate_anthropic_auth()

    def test_requires_an_authentication_value(self):
        loaded = self.load({})

        with self.assertRaisesRegex(RuntimeError, "is required"):
            loaded.validate_anthropic_auth()


class ConfigRequestOptionTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults_to_the_anthropic_behaviour(self):
        loaded = self.load({})

        loaded.validate_anthropic_options()
        self.assertEqual("default", loaded.anthropic_thinking_mode)
        self.assertEqual("forced", loaded.anthropic_tool_choice_mode)

    def test_keeps_the_configured_values(self):
        loaded = self.load({
            "ANTHROPIC_THINKING_MODE": "disabled",
            "ANTHROPIC_TOOL_CHOICE_MODE": "auto",
        })

        loaded.validate_anthropic_options()
        self.assertEqual("disabled", loaded.anthropic_thinking_mode)
        self.assertEqual("auto", loaded.anthropic_tool_choice_mode)

    def test_rejects_an_unknown_thinking_mode(self):
        loaded = self.load({"ANTHROPIC_THINKING_MODE": "off"})

        with self.assertRaisesRegex(RuntimeError, "ANTHROPIC_THINKING_MODE"):
            loaded.validate_anthropic_options()

    def test_rejects_an_unknown_tool_choice_mode(self):
        loaded = self.load({"ANTHROPIC_TOOL_CHOICE_MODE": "any"})

        with self.assertRaisesRegex(RuntimeError,
                                    "ANTHROPIC_TOOL_CHOICE_MODE"):
            loaded.validate_anthropic_options()


class ClientConstructionTest(unittest.TestCase):

    def build_client(self, api_key=None, auth_token=None, base_url=None):
        client = object()
        anthropic = types.SimpleNamespace(
            Anthropic=mock.Mock(return_value=client),
        )
        with mock.patch.dict(sys.modules, {"anthropic": anthropic}):
            result = summarizer._build_client(api_key, auth_token, base_url)
        return result, anthropic.Anthropic

    def test_builds_standard_anthropic_client(self):
        client, constructor = self.build_client(api_key="key")

        self.assertIsNotNone(client)
        constructor.assert_called_once_with(api_key="key")

    def test_builds_compatible_api_client(self):
        client, constructor = self.build_client(
            auth_token="uuid:secret",
            base_url="https://api.example.test",
        )

        self.assertIsNotNone(client)
        constructor.assert_called_once_with(
            auth_token="uuid:secret",
            base_url="https://api.example.test",
        )

    def test_rejects_ambiguous_authentication(self):
        with self.assertRaisesRegex(RuntimeError, "either"):
            self.build_client(api_key="key", auth_token="token")


class RequestBuildTest(unittest.TestCase):

    def build(self, thinking_mode="default", tool_choice_mode="forced"):
        entry = Entry(source_type="paper", title="A paper",
                      url="https://example.test/1")
        return summarizer._build_request([entry], "test-model", 6,
                                         thinking_mode, tool_choice_mode)

    def test_omits_the_thinking_parameter_by_default(self):
        request = self.build()

        self.assertNotIn("extra_body", request)
        self.assertEqual("test-model", request["model"])

    def test_disables_the_thinking_output_on_request(self):
        request = self.build(thinking_mode="disabled")

        self.assertEqual({"thinking": {"type": "disabled"}},
                         request["extra_body"])

    def test_names_the_tool_by_default(self):
        request = self.build()

        self.assertEqual({"type": "tool", "name": "build_report"},
                         request["tool_choice"])

    def test_lets_the_model_choose_the_tool_on_request(self):
        request = self.build(tool_choice_mode="auto")

        self.assertEqual(
            {"type": "auto", "disable_parallel_tool_use": True},
            request["tool_choice"],
        )


class ResponseParsingTest(unittest.TestCase):

    def message(self, blocks, stop_reason):
        return types.SimpleNamespace(content=blocks, stop_reason=stop_reason)

    def tool_use(self, name, tool_input):
        return types.SimpleNamespace(type="tool_use", name=name,
                                     input=tool_input)

    def test_returns_the_build_report_arguments(self):
        payload = {"topics": [{"title": "A topic"}]}
        message = self.message([self.tool_use("build_report", payload)],
                               "tool_use")

        self.assertEqual(payload, summarizer._extract_tool_input(message))

    def test_parses_arguments_given_as_a_json_string(self):
        payload = {"topics": []}
        message = self.message(
            [self.tool_use("build_report", json.dumps(payload))], "tool_use")

        self.assertEqual(payload, summarizer._extract_tool_input(message))

    def test_reports_arguments_cut_off_by_the_budget(self):
        message = self.message(
            [self.tool_use("build_report", {"topics": [{"title": "Cut"}]})],
            "max_tokens")

        with self.assertRaisesRegex(RuntimeError, "report is truncated"):
            summarizer._extract_tool_input(message)

    def test_reports_arguments_that_are_not_valid_json(self):
        message = self.message(
            [self.tool_use("build_report", '{"topics": [{"category":')],
            "tool_use")

        with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
            summarizer._extract_tool_input(message)

    def test_ignores_a_call_to_another_tool(self):
        message = self.message([self.tool_use("other_tool", {"topics": []})],
                               "tool_use")

        with self.assertRaisesRegex(RuntimeError, "no build_report tool call"):
            summarizer._extract_tool_input(message)

    def test_reports_a_budget_spent_on_thinking(self):
        message = self.message(
            [types.SimpleNamespace(type="thinking", thinking="...")],
            "max_tokens")

        with self.assertRaisesRegex(RuntimeError, "exhausted max_tokens"):
            summarizer._extract_tool_input(message)

    def test_reports_a_plain_text_answer(self):
        message = self.message(
            [types.SimpleNamespace(type="text", text="Sorry.")], "end_turn")

        with self.assertRaisesRegex(
                RuntimeError, "stop_reason=end_turn, content_types=text"):
            summarizer._extract_tool_input(message)


class EmptyInputTest(unittest.TestCase):

    def test_does_not_call_the_api_without_entries(self):
        with mock.patch.object(summarizer, "_build_client") as build_client:
            self.assertEqual([], summarizer.summarize([], "key", "model", 6))

        build_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
