#!/usr/bin/env python
# -*- coding: utf-8 -*-

import os
import sys
import types
import unittest
from unittest import mock

import config
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
        constructor.assert_called_once_with(max_retries=0, api_key="key")

    def test_builds_compatible_api_client(self):
        client, constructor = self.build_client(
            auth_token="uuid:secret",
            base_url="https://api.example.test",
        )

        self.assertIsNotNone(client)
        constructor.assert_called_once_with(
            max_retries=0,
            auth_token="uuid:secret",
            base_url="https://api.example.test",
        )

    def test_rejects_ambiguous_authentication(self):
        with self.assertRaisesRegex(RuntimeError, "either"):
            self.build_client(api_key="key", auth_token="token")


if __name__ == "__main__":
    unittest.main()
