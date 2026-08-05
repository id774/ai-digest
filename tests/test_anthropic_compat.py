#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_anthropic_compat.py: Tests for the Anthropic compatible backend
#
#  Description:
#  This test suite covers the summarizer that speaks the Anthropic
#  protocol, from the settings that authenticate it to the reading of
#  what it answers. Exactly one credential is accepted, an API key or a
#  bearer token, because the two describe different requests and a
#  configuration carrying both does not say which was meant.
#
#  Most of the cases are about the answer. The run asks for one tool
#  call and gets back something else often enough that each way of
#  failing is reported on its own: arguments cut off by the token
#  budget, arguments that are not valid JSON, a call to another tool, a
#  budget spent on thinking before the tool was reached, and a plain
#  text answer, whose message names the stop reason and the block types
#  so that a log line says what came back.
#
#  The prompt cases pin that the collected window is announced to the
#  model, and the last case pins that an empty collection costs no
#  request at all.
#
#  No request is made. The anthropic package is replaced in sys.modules
#  and the client is stubbed, so the suite needs neither the credential
#  nor a network.
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
#      python -m unittest tests.test_anthropic_compat
#
#  Test Cases:
#    - Load API key authentication.
#    - Load bearer authentication together with a base URL.
#    - Reject a configuration carrying more than one credential.
#    - Require a credential.
#    - Default the thinking and tool choice modes to the Anthropic behaviour.
#    - Keep the configured thinking and tool choice modes.
#    - Reject an unknown thinking mode, and an unknown tool choice mode.
#    - Build a standard Anthropic client from an API key.
#    - Build a compatible client from a bearer token and a base URL.
#    - Reject ambiguous authentication when building the client.
#    - Omit the thinking parameter by default, and disable it on request.
#    - Name the tool by default, and leave the choice to the model on request.
#    - Return the arguments of a build_report call.
#    - Parse arguments given as a JSON string.
#    - Report arguments cut off by the token budget as truncated.
#    - Report arguments that are not valid JSON.
#    - Ignore a call to another tool.
#    - Report a budget spent on thinking.
#    - Report a plain text answer, naming the stop reason and block types.
#    - Announce the default window and the configured one in the prompt.
#    - Pass the window through summarize().
#    - Call nothing when there is no entry to summarize.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the anthropic package is stubbed, never imported)
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

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
        loaded = self.load({"SUMMARIZER_API_KEY": "key"})

        loaded.validate_summarizer_auth()
        self.assertEqual("key", loaded.summarizer_api_key)
        self.assertIsNone(loaded.summarizer_auth_token)

    def test_loads_bearer_authentication_and_base_url(self):
        loaded = self.load({
            "SUMMARIZER_AUTH_TOKEN": "uuid:secret",
            "SUMMARIZER_BASE_URL": "https://api.example.test",
        })

        loaded.validate_summarizer_auth()
        self.assertEqual("uuid:secret", loaded.summarizer_auth_token)
        self.assertEqual("https://api.example.test",
                         loaded.summarizer_base_url)

    def test_rejects_multiple_authentication_values(self):
        loaded = self.load({
            "SUMMARIZER_API_KEY": "key",
            "SUMMARIZER_AUTH_TOKEN": "token",
        })

        with self.assertRaisesRegex(RuntimeError, "only one"):
            loaded.validate_summarizer_auth()

    def test_requires_an_authentication_value(self):
        loaded = self.load({})

        with self.assertRaisesRegex(RuntimeError, "is required"):
            loaded.validate_summarizer_auth()


class ConfigRequestOptionTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults_to_the_anthropic_behaviour(self):
        loaded = self.load({})

        loaded.validate_protocol_options()
        self.assertEqual("default", loaded.summarizer_thinking_mode)
        self.assertEqual("forced", loaded.summarizer_tool_choice_mode)

    def test_keeps_the_configured_values(self):
        loaded = self.load({
            "SUMMARIZER_THINKING_MODE": "disabled",
            "SUMMARIZER_TOOL_CHOICE_MODE": "auto",
        })

        loaded.validate_protocol_options()
        self.assertEqual("disabled", loaded.summarizer_thinking_mode)
        self.assertEqual("auto", loaded.summarizer_tool_choice_mode)

    def test_rejects_an_unknown_thinking_mode(self):
        loaded = self.load({"SUMMARIZER_THINKING_MODE": "off"})

        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_THINKING_MODE"):
            loaded.validate_protocol_options()

    def test_rejects_an_unknown_tool_choice_mode(self):
        # 'any' used to stand for an unknown value here; it is a
        # supported mode now, so the check needs a real typo.
        loaded = self.load({"SUMMARIZER_TOOL_CHOICE_MODE": "always"})

        with self.assertRaisesRegex(RuntimeError,
                                    "SUMMARIZER_TOOL_CHOICE_MODE"):
            loaded.validate_protocol_options()


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


class PromptWindowTest(unittest.TestCase):

    def entry(self):
        return Entry(source_type="news", title="Title",
                     url="https://example.test/a", summary="Summary.",
                     published="2026-08-02T00:00:00+00:00", origin="Feed")

    def test_announces_the_default_window(self):
        prompt = summarizer.build_prompt([self.entry()], 6)

        self.assertIn("過去 24 時間", prompt)

    def test_announces_the_configured_window(self):
        prompt = summarizer.build_prompt([self.entry()], 6, 72)

        self.assertIn("過去 72 時間", prompt)
        self.assertNotIn("過去 24 時間", prompt)

    def test_summarize_passes_the_window_through(self):
        client = mock.Mock()
        client.messages.create.return_value = types.SimpleNamespace(
            content=[types.SimpleNamespace(type="tool_use",
                                           name="build_report",
                                           input={"topics": []})],
            stop_reason="tool_use", usage=None, id="m-1", model="m")
        with mock.patch.object(summarizer, "_build_client",
                               return_value=client):
            summarizer.summarize([self.entry()], api_key="k", model="m",
                                 max_topics=6, lookback_hours=72)

        request = client.messages.create.call_args.kwargs
        self.assertIn("過去 72 時間", request["messages"][0]["content"])


class EmptyInputTest(unittest.TestCase):

    def test_does_not_call_the_api_without_entries(self):
        with mock.patch.object(summarizer, "_build_client") as build_client:
            self.assertEqual([], summarizer.summarize([], "key", "model", 6))

        build_client.assert_not_called()


if __name__ == "__main__":
    unittest.main()
