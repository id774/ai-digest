#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_openai_compat.py: Tests for ai_digest/analyzer/openai_compat.py
#
#  Description:
#  This test suite covers the OpenAI compatible summarizer backend. It
#  pins that the function tool is the Anthropic schema reused rather
#  than a second copy that could drift from it, that the request names
#  the tool it wants called, and that the collected window reaches the
#  prompt.
#
#  The reading of an answer is where most of the cases sit. A call by
#  another name, a missing call, arguments that are not JSON and
#  arguments that are not an object are each refused with a message that
#  says which, and an answer cut off by the token limit is reported as
#  truncated rather than as malformed, because only one of the two is
#  answered by raising the limit.
#
#  The client cases cover the construction of the SDK client, including
#  the error raised when the openai package is absent: it names the
#  install command, since that package is deliberately left out of
#  requirements.txt.
#
#  No request is made. The openai package is replaced in sys.modules, so
#  the suite needs neither the dependency nor a network.
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
#      python -m unittest tests.test_openai_compat
#
#  Test Cases:
#    - Carry the collected window into the prompt.
#    - Build the function tool out of the Anthropic input schema.
#    - Read the arguments of a build_report call.
#    - Reject a tool call made by another name.
#    - Reject an answer that carries no tool call.
#    - Report an answer cut off by the token limit as truncated.
#    - Reject arguments that are not valid JSON.
#    - Reject arguments that are not an object.
#    - Reject an answer that carries no choice.
#    - Call nothing when there is no entry to summarize.
#    - Name the tool in the request and in tool_choice.
#    - Build topics through the validation shared with the Anthropic path.
#    - Drop a topic citing a source index that does not exist.
#    - Pass the base URL and the retry budget to the SDK.
#    - Omit the retry budget when it is not given.
#    - Name the install command when the openai package is missing.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only (the openai package is stubbed, never imported)
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import sys
import types
import unittest
from types import SimpleNamespace
from unittest import mock

from ai_digest import Entry
from ai_digest.analyzer import openai_compat


def _entry(title="Title"):
    return Entry(source_type="news", title=title,
                 url="https://example.test/a", summary="Summary.",
                 published="2026-08-02T00:00:00+00:00", origin="Feed")


def _response(arguments='{"topics": []}', name="build_report",
              finish_reason="tool_calls", with_call=True):
    call = SimpleNamespace(
        function=SimpleNamespace(name=name, arguments=arguments))
    message = SimpleNamespace(tool_calls=[call] if with_call else [])
    return SimpleNamespace(
        id="resp-1",
        model="preview/Kimi-K2.6",
        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=20),
        choices=[SimpleNamespace(finish_reason=finish_reason,
                                 message=message)],
    )


class PromptWindowTest(unittest.TestCase):

    def test_passes_the_window_through(self):
        client = mock.Mock()
        client.chat.completions.create.return_value = _response()
        with mock.patch.object(openai_compat, "_build_client",
                               return_value=client):
            openai_compat.summarize([_entry()], api_key="k", model="m",
                                    max_topics=6, lookback_hours=72)

        request = client.chat.completions.create.call_args.kwargs
        self.assertIn("過去 72 時間", request["messages"][1]["content"])


class FunctionToolTest(unittest.TestCase):

    def test_reuses_the_anthropic_schema(self):
        tool = openai_compat.build_function_tool()

        self.assertEqual("function", tool["type"])
        self.assertEqual("build_report", tool["function"]["name"])
        self.assertEqual(openai_compat.BUILD_REPORT_TOOL["input_schema"],
                         tool["function"]["parameters"])


class ExtractArgumentsTest(unittest.TestCase):

    def test_reads_the_arguments(self):
        payload = openai_compat._extract_arguments(
            _response('{"topics": [{"title": "a"}]}'))

        self.assertEqual([{"title": "a"}], payload["topics"])

    def test_rejects_a_call_by_another_name(self):
        with self.assertRaisesRegex(RuntimeError, "no build_report"):
            openai_compat._extract_arguments(_response(name="something_else"))

    def test_rejects_a_missing_call(self):
        with self.assertRaisesRegex(RuntimeError, "no build_report"):
            openai_compat._extract_arguments(
                _response(with_call=False, finish_reason="stop"))

    def test_reports_a_truncated_answer_as_truncated(self):
        with self.assertRaisesRegex(RuntimeError, "token limit"):
            openai_compat._extract_arguments(
                _response('{"topics": [', finish_reason="length"))

    def test_rejects_unparsable_arguments(self):
        with self.assertRaisesRegex(RuntimeError, "not valid JSON"):
            openai_compat._extract_arguments(_response("{not json"))

    def test_rejects_arguments_that_are_not_an_object(self):
        with self.assertRaisesRegex(RuntimeError, "not an object"):
            openai_compat._extract_arguments(_response("[1, 2]"))

    def test_rejects_an_empty_choice_list(self):
        with self.assertRaisesRegex(RuntimeError, "no choice"):
            openai_compat._extract_arguments(SimpleNamespace(choices=[]))


class SummarizeTest(unittest.TestCase):

    def build(self, response, **kwargs):
        client = mock.Mock()
        client.chat.completions.create.return_value = response
        with mock.patch.object(openai_compat, "_build_client",
                               return_value=client):
            topics = openai_compat.summarize(
                [_entry()], api_key="key", model="m", max_topics=6, **kwargs)
        return topics, client.chat.completions.create

    def test_no_entry_calls_nothing(self):
        with mock.patch.object(openai_compat, "_build_client") as builder:
            self.assertEqual([], openai_compat.summarize(
                [], api_key="key", model="m", max_topics=6))
        builder.assert_not_called()

    def test_names_the_tool_in_the_request(self):
        _topics, create = self.build(_response())

        request = create.call_args.kwargs
        self.assertEqual(
            {"type": "function", "function": {"name": "build_report"}},
            request["tool_choice"])
        self.assertEqual("build_report",
                         request["tools"][0]["function"]["name"])

    def test_builds_topics_through_the_shared_validation(self):
        arguments = ('{"topics": [{"category": "c", "title": "t", '
                     '"bullets": ["b"], "source_indexes": [0]}]}')
        topics, _create = self.build(_response(arguments))

        self.assertEqual(1, len(topics))
        self.assertEqual("t", topics[0].title)
        self.assertEqual("https://example.test/a", topics[0].sources[0]["url"])

    def test_drops_a_topic_without_a_usable_source(self):
        # to_topics() is shared with the Anthropic path, so a
        # hallucinated index is dropped here too.
        arguments = ('{"topics": [{"category": "c", "title": "t", '
                     '"bullets": ["b"], "source_indexes": [99]}]}')
        topics, _create = self.build(_response(arguments))

        self.assertEqual([], topics)


class ClientTest(unittest.TestCase):

    def build(self, **kwargs):
        constructor = mock.Mock(return_value=object())
        module = types.SimpleNamespace(OpenAI=constructor)
        with mock.patch.dict(sys.modules, {"openai": module}):
            openai_compat._build_client(**kwargs)
        return constructor

    def test_passes_the_base_url_and_retries(self):
        constructor = self.build(api_key="key",
                                 base_url="https://api.example.test/v1",
                                 max_retries=0)

        constructor.assert_called_once_with(
            api_key="key", base_url="https://api.example.test/v1",
            max_retries=0)

    def test_omits_retries_when_not_given(self):
        constructor = self.build(api_key="key", base_url=None,
                                 max_retries=None)

        constructor.assert_called_once_with(api_key="key")

    def test_missing_package_names_the_install_command(self):
        real_import = __import__

        def fail(name, *args, **kwargs):
            if name == "openai":
                raise ImportError("no openai")
            return real_import(name, *args, **kwargs)

        with mock.patch("builtins.__import__", side_effect=fail):
            with self.assertRaisesRegex(RuntimeError, "pip install openai"):
                openai_compat._build_client("key", None, None)


if __name__ == "__main__":
    unittest.main()
