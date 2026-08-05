#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_config.py: Tests for config.py
#
#  Description:
#  This test suite covers the settings that decide which endpoint a run
#  addresses. The backend name is checked strictly on purpose: a typo
#  must not quietly select an API backend and spend requests on what was
#  meant to be an offline run, and a superseded name is refused with the
#  value that replaced it, because a generic list of the accepted values
#  does not say which one a vendor name became.
#
#  The legacy variable cases close a hazard of their own. Names such as
#  ANTHROPIC_BASE_URL are what the vendor SDKs and other tools read on
#  their own, so a value exported for one of those used to decide where
#  a digest went. Presence is refused here, not the value, which is why
#  an exported but empty name is refused too.
#
#  The remaining cases cover the User-Agent, where an empty setting
#  reads as unset rather than sending an empty header the feed hosts are
#  free to refuse, and the model, which falls back on a known Claude
#  model under the Anthropic protocol and has nothing to fall back on
#  under the OpenAI one, because the models an endpoint offers are its
#  own.
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
#      python -m unittest tests.test_config
#
#  Test Cases:
#    - Default to the Anthropic protocol when the backend is unset or empty.
#    - Accept the plain backend, normalizing case and surrounding space.
#    - Reject a misspelled backend rather than selecting an API one.
#    - Name the replacement of a superseded backend.
#    - Reject a backend value carrying a trailing comment.
#    - Keep require_api_key gone, validate_summarizer_auth() being the check.
#    - Default the User-Agent when it is unset or empty.
#    - Keep a configured User-Agent, stripped of surrounding space.
#    - Refuse every superseded variable by name, naming its replacement.
#    - Refuse a superseded name that is exported but empty.
#    - Load a configuration that uses the current names.
#    - Fall back on a Claude model under the Anthropic protocol.
#    - Have no default model under the OpenAI protocol.
#    - Let a configured model win on either protocol.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import os
import unittest
from unittest import mock

import config


class SummarizerBackendTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults_to_the_anthropic_protocol_when_unset(self):
        loaded = self.load({})

        loaded.validate_summarizer_backend()
        self.assertEqual("anthropic-compatible", loaded.summarizer_backend)

    def test_defaults_to_the_anthropic_protocol_when_empty(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "  "})

        loaded.validate_summarizer_backend()
        self.assertEqual("anthropic-compatible", loaded.summarizer_backend)

    def test_accepts_plain(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "plain"})

        loaded.validate_summarizer_backend()
        self.assertEqual("plain", loaded.summarizer_backend)

    def test_normalizes_case_and_surrounding_space(self):
        loaded = self.load({"SUMMARIZER_BACKEND": " Plain "})

        loaded.validate_summarizer_backend()
        self.assertEqual("plain", loaded.summarizer_backend)

    def test_rejects_a_misspelled_backend(self):
        # The whole point of the check: a typo must not quietly select
        # an API backend and spend requests on an offline run.
        loaded = self.load({"SUMMARIZER_BACKEND": "plian"})

        self.assertEqual("plian", loaded.summarizer_backend)
        with self.assertRaisesRegex(RuntimeError, "plian"):
            loaded.validate_summarizer_backend()

    def test_names_the_replacement_of_a_superseded_backend(self):
        # 'claude' and 'openai' named a vendor rather than a wire
        # protocol. The generic list does not say which of the three
        # new values each became, so the message says it.
        for old, new in (("claude", "anthropic-compatible"),
                         ("openai", "openai-compatible")):
            loaded = self.load({"SUMMARIZER_BACKEND": old})

            with self.assertRaisesRegex(RuntimeError, new):
                loaded.validate_summarizer_backend()

    def test_rejects_a_value_carrying_a_trailing_comment(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "plain # offline"})

        with self.assertRaisesRegex(RuntimeError, "expected one of"):
            loaded.validate_summarizer_backend()

    def test_require_api_key_is_gone(self):
        # It was never called; validate_summarizer_auth() is the check.
        self.assertFalse(hasattr(config.Config, "require_api_key"))


class UserAgentTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults_when_unset(self):
        self.assertEqual(config.DEFAULT_USER_AGENT,
                         self.load({}).user_agent)

    def test_defaults_when_empty(self):
        # 'USER_AGENT=' in .env used to send an empty header, which the
        # feed hosts are free to refuse.
        self.assertEqual(config.DEFAULT_USER_AGENT,
                         self.load({"USER_AGENT": "   "}).user_agent)

    def test_keeps_a_configured_identity(self):
        self.assertEqual("mine/2.0",
                         self.load({"USER_AGENT": " mine/2.0 "}).user_agent)


class LegacyVariableTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_refuses_every_superseded_name(self):
        for old, new in config.LEGACY_VARIABLES.items():
            with self.assertRaises(RuntimeError) as raised:
                self.load({old: "value"})

            self.assertIn(old, str(raised.exception))
            self.assertIn(new, str(raised.exception))

    def test_refuses_a_name_that_is_exported_but_empty(self):
        # The hazard this closes: ANTHROPIC_BASE_URL is what the
        # Anthropic SDK and other tools read on their own, so a value
        # exported for one of those used to decide where a digest went.
        # Presence is refused, not the value.
        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_BASE_URL"):
            self.load({"ANTHROPIC_BASE_URL": ""})

    def test_a_configuration_using_the_new_names_loads(self):
        loaded = self.load({
            "SUMMARIZER_API_KEY": "key",
            "SUMMARIZER_BASE_URL": "https://api.example.test",
        })

        self.assertEqual("key", loaded.summarizer_api_key)


class ResolvedModelTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_falls_back_on_a_claude_model_for_the_anthropic_protocol(self):
        loaded = self.load({})

        self.assertEqual(config.DEFAULT_ANTHROPIC_MODEL,
                         loaded.resolved_model)
        loaded.validate_summarizer_model()

    def test_has_no_default_for_the_openai_protocol(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible"})

        self.assertEqual("", loaded.resolved_model)

    def test_a_configured_model_wins_on_either_protocol(self):
        for backend in ("anthropic-compatible", "openai-compatible"):
            loaded = self.load({"SUMMARIZER_BACKEND": backend,
                                "SUMMARIZER_MODEL": " preview/Kimi-K2.6 "})

            self.assertEqual("preview/Kimi-K2.6", loaded.resolved_model)


if __name__ == "__main__":
    unittest.main()
