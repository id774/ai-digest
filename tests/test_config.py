#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import unittest
from unittest import mock

import config


class SummarizerBackendTest(unittest.TestCase):

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_defaults_to_claude_when_unset(self):
        loaded = self.load({})

        loaded.validate_summarizer_backend()
        self.assertEqual("claude", loaded.summarizer_backend)

    def test_defaults_to_claude_when_empty(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "  "})

        loaded.validate_summarizer_backend()
        self.assertEqual("claude", loaded.summarizer_backend)

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
        # the Claude backend and spend API calls on an offline run.
        loaded = self.load({"SUMMARIZER_BACKEND": "plian"})

        self.assertEqual("plian", loaded.summarizer_backend)
        with self.assertRaisesRegex(RuntimeError, "plian"):
            loaded.validate_summarizer_backend()

    def test_rejects_a_value_carrying_a_trailing_comment(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "plain # offline"})

        with self.assertRaisesRegex(RuntimeError, "expected one of"):
            loaded.validate_summarizer_backend()

    def test_require_api_key_is_gone(self):
        # It was never called; validate_anthropic_auth() is the check.
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


if __name__ == "__main__":
    unittest.main()
