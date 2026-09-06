#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tests/test_config_scope.py: Tests for execution-path configuration scope
#
#  Description:
#  This test suite covers the scope matrix that keeps each execution
#  path from depending on settings it never uses: the viewer resolves
#  DATA_DIR and PORT alone, 'list' resolves DATA_DIR alone, 'render' and
#  'demo' add only what they draw with, and 'run' resolves the full
#  batch scope except PORT, which only the viewer reads.
#
#  The isolation cases are the point of the suite. A setting outside a
#  scope is never even looked at, so a malformed batch setting, an
#  unknown backend, a missing credential, an unusable font path or a
#  legacy ANTHROPIC_*/OPENAI_* name must not stop the viewer, 'list',
#  'render' or 'demo'; conversely, an invalid PORT must not stop 'run',
#  and each scope still rejects its own invalid settings, an unusable
#  explicit font path included. A dedicated case imports app.py itself,
#  because the viewer resolves its configuration at import time and
#  that is where a regression would actually surface.
#
#  The credential isolation case guards the sharper property behind the
#  viewer's independence: a summarizer credential sitting in .env must
#  reach neither the viewer's Config nor the process environment on the
#  viewer's account. The deployment case reads deploy/ai-digest.service
#  as text and pins that the shared batch .env is no longer wired into
#  the viewer unit, and that its port has one source of truth.
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
#      python -m unittest tests.test_config_scope
#
#  Test Cases:
#    - Resolve exactly the settings section 6.1 assigns each scope.
#    - Keep the exported-environment-over-.env-over-default precedence
#      for a relevant setting, without exporting an unrelated .env entry,
#      and never fall an invalid exported font path back to a valid .env one.
#    - Let the viewer and 'list' ignore a batch-only or legacy setting
#      error, an unusable AI_DIGEST_FONT_PATH included.
#    - Let 'render', 'demo' and 'run' ignore what is out of their own
#      scope, and still reject their own invalid setting, unusable font
#      path and (for 'run') legacy endpoint variable alike.
#    - Import app.py surviving a batch-only setting error, and failing
#      on an invalid PORT.
#    - Keep a summarizer credential out of the viewer's Config and out
#      of the process environment.
#    - Keep the shared batch .env out of the viewer's systemd unit, and
#      its port to one source of truth.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt (the app.py case imports Flask; font cases use Pillow)
#
#  Version History:
#  v1.0 2026-09-06
#       Initial release, covering font path scope isolation as well.
#
########################################################################

import importlib
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

import config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_with(loader, environment):
    """ Call a scoped loader under a clean, fully controlled environment. """
    with mock.patch.dict(os.environ, environment, clear=True):
        with mock.patch.object(config, "load_dotenv", None):
            return loader()


def load_with_dotenv(loader, environment, dotenv):
    """ Call a scoped loader with a fake, non-exported .env source. """
    with mock.patch.dict(os.environ, environment, clear=True):
        with mock.patch.object(config, "load_dotenv", lambda *a, **k: None):
            with mock.patch.object(config, "dotenv_values",
                                   return_value=dotenv):
                return loader()


class ScopeMatrixTest(unittest.TestCase):
    """ Each loader resolves exactly the settings section 6.1 assigns it. """

    def test_viewer_resolves_data_dir_and_port(self):
        loaded = load_with(config.load_viewer_config,
                           {"DATA_DIR": "/tmp/scope-a", "PORT": "4000"})

        self.assertEqual(os.path.abspath("/tmp/scope-a"), loaded.data_dir)
        self.assertEqual(4000, loaded.port)

    def test_list_resolves_data_dir_alone(self):
        loaded = load_with(config.load_list_config,
                           {"DATA_DIR": "/tmp/scope-b", "PORT": "4000"})

        self.assertEqual(os.path.abspath("/tmp/scope-b"), loaded.data_dir)
        self.assertEqual(3000, loaded.port)  # PORT is out of scope here

    def test_render_resolves_its_scope(self):
        loaded = load_with(config.load_render_config, {
            "DATA_DIR": "/tmp/scope-c",
            "LOOKBACK_HOURS": "48",
        })

        self.assertEqual(os.path.abspath("/tmp/scope-c"), loaded.data_dir)
        self.assertEqual(48, loaded.lookback_hours)

    def test_demo_resolves_its_scope(self):
        loaded = load_with(config.load_demo_config, {
            "DATA_DIR": "/tmp/scope-d",
            "MAX_TOPICS": "3",
            "LOOKBACK_HOURS": "12",
        })

        self.assertEqual(3, loaded.max_topics)
        self.assertEqual(12, loaded.lookback_hours)

    def test_run_resolves_the_batch_scope_but_never_port(self):
        loaded = load_with(config.load_run_config, {
            "PORT": "not-a-number",
            "SUMMARIZER_MAX_RETRIES": "3",
        })

        self.assertEqual(3, loaded.summarizer_max_retries)
        self.assertEqual(3000, loaded.port)  # default; PORT never read


class PrecedenceTest(unittest.TestCase):
    """ Precedence within a scope stays exported > .env > default. """

    def test_exported_wins_over_dotenv(self):
        loaded = load_with_dotenv(config.load_list_config,
                                  {"DATA_DIR": "/exported"},
                                  {"DATA_DIR": "/from-dotenv"})

        self.assertEqual(os.path.abspath("/exported"), loaded.data_dir)

    def test_dotenv_wins_over_the_default(self):
        loaded = load_with_dotenv(config.load_list_config, {},
                                  {"DATA_DIR": "/from-dotenv"})

        self.assertEqual(os.path.abspath("/from-dotenv"), loaded.data_dir)

    def test_an_unrelated_dotenv_entry_is_not_exported(self):
        # The point of resolving .env through a plain dict instead of
        # load_dotenv(): a scope that never asked for a setting must
        # not find it sitting in os.environ afterward.
        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(config, "load_dotenv",
                                   lambda *a, **k: None):
                with mock.patch.object(
                        config, "dotenv_values",
                        return_value={"SUMMARIZER_API_KEY": "dummy-secret"}):
                    config.load_list_config()

            self.assertNotIn("SUMMARIZER_API_KEY", os.environ)

    def test_an_invalid_exported_font_path_does_not_fall_back_to_dotenv(self):
        # An unusable explicit value at the higher precedence source
        # must fail outright, never fall through to a usable one below
        # it - not even a valid path sitting right there in .env.
        with mock.patch.object(config, "is_usable_font_path",
                               side_effect=lambda p: p == "/valid/font.ttf"):
            with self.assertRaisesRegex(RuntimeError, "AI_DIGEST_FONT_PATH"):
                load_with_dotenv(
                    config.load_run_config,
                    {"AI_DIGEST_FONT_PATH": "/bad/font.ttf"},
                    {"AI_DIGEST_FONT_PATH": "/valid/font.ttf"})


class ViewerIsolationTest(unittest.TestCase):

    def test_ignores_batch_only_and_legacy_errors(self):
        environment = {
            "SUMMARIZER_MAX_RETRIES": "not-a-number",
            "SUMMARIZER_BACKEND": "unknown-backend",
            "ANTHROPIC_BASE_URL": "https://example.test",
            "HTTP_TIMEOUT": "not-a-number",
            "AI_DIGEST_FONT_PATH": "/no/such/font.ttf",
        }

        loaded = load_with(config.load_viewer_config, environment)

        self.assertEqual(3000, loaded.port)

    def test_still_rejects_its_own_invalid_port(self):
        with self.assertRaisesRegex(RuntimeError, "PORT"):
            load_with(config.load_viewer_config, {"PORT": "not-a-number"})


class ListIsolationTest(unittest.TestCase):

    def test_ignores_batch_only_and_legacy_errors(self):
        environment = {
            "PORT": "not-a-number",
            "SUMMARIZER_MAX_RETRIES": "not-a-number",
            "ANTHROPIC_BASE_URL": "https://example.test",
            "AI_DIGEST_FONT_PATH": "/no/such/font.ttf",
        }

        loaded = load_with(config.load_list_config, environment)

        self.assertTrue(loaded.data_dir)


class RenderIsolationTest(unittest.TestCase):

    def test_ignores_endpoint_collector_and_viewer_only_errors(self):
        environment = {
            "PORT": "not-a-number",
            "SUMMARIZER_BACKEND": "unknown-backend",
            "ANTHROPIC_BASE_URL": "https://example.test",
            "ARXIV_MAX_RESULTS": "not-a-number",
        }

        loaded = load_with(config.load_render_config, environment)

        self.assertEqual(24, loaded.lookback_hours)

    def test_still_rejects_its_own_invalid_lookback_hours(self):
        with self.assertRaisesRegex(RuntimeError, "LOOKBACK_HOURS"):
            load_with(config.load_render_config, {"LOOKBACK_HOURS": "soon"})

    def test_still_rejects_its_own_unusable_font_path(self):
        with self.assertRaisesRegex(RuntimeError, "AI_DIGEST_FONT_PATH"):
            load_with(config.load_render_config,
                     {"AI_DIGEST_FONT_PATH": "/no/such/font.ttf"})


class DemoIsolationTest(unittest.TestCase):

    def test_ignores_endpoint_collector_and_viewer_only_errors(self):
        environment = {
            "PORT": "not-a-number",
            "SUMMARIZER_BACKEND": "unknown-backend",
            "ANTHROPIC_BASE_URL": "https://example.test",
        }

        loaded = load_with(config.load_demo_config, environment)

        self.assertEqual(6, loaded.max_topics)

    def test_still_rejects_its_own_invalid_max_topics(self):
        with self.assertRaisesRegex(RuntimeError, "MAX_TOPICS"):
            load_with(config.load_demo_config, {"MAX_TOPICS": "0"})

    def test_still_rejects_its_own_unusable_font_path(self):
        with self.assertRaisesRegex(RuntimeError, "AI_DIGEST_FONT_PATH"):
            load_with(config.load_demo_config,
                     {"AI_DIGEST_FONT_PATH": "/no/such/font.ttf"})


class RunIsolationTest(unittest.TestCase):

    def test_ignores_an_invalid_port(self):
        loaded = load_with(config.load_run_config, {"PORT": "not-a-number"})

        self.assertEqual(3000, loaded.port)

    def test_still_rejects_a_legacy_endpoint_variable(self):
        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_BASE_URL"):
            load_with(config.load_run_config,
                     {"ANTHROPIC_BASE_URL": "https://example.test"})

    def test_still_rejects_its_own_invalid_setting(self):
        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_MAX_RETRIES"):
            load_with(config.load_run_config,
                     {"SUMMARIZER_MAX_RETRIES": "not-a-number"})

    def test_still_rejects_its_own_unusable_font_path(self):
        with self.assertRaisesRegex(RuntimeError, "AI_DIGEST_FONT_PATH"):
            load_with(config.load_run_config,
                     {"AI_DIGEST_FONT_PATH": "/no/such/font.ttf"})


class ViewerImportIsolationTest(unittest.TestCase):
    """ app.py resolves its configuration at import time. """

    def reload_app(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                if "app" in sys.modules:
                    return importlib.reload(sys.modules["app"])
                return importlib.import_module("app")

    def test_import_survives_a_batch_only_error(self):
        with tempfile.TemporaryDirectory() as data_dir:
            module = self.reload_app({
                "DATA_DIR": data_dir,
                "SUMMARIZER_MAX_RETRIES": "not-a-number",
                "ANTHROPIC_BASE_URL": "https://example.test",
                "AI_DIGEST_FONT_PATH": "/no/such/font.ttf",
            })

            self.assertEqual(3000, module.config.port)

    def test_import_fails_on_an_invalid_port(self):
        with tempfile.TemporaryDirectory() as data_dir:
            with self.assertRaises(RuntimeError):
                self.reload_app({"DATA_DIR": data_dir, "PORT": "not-a-number"})


class CredentialIsolationTest(unittest.TestCase):
    """ A batch credential in .env must never reach the viewer. """

    def test_viewer_config_does_not_hold_the_credential(self):
        dotenv = {
            "DATA_DIR": "/tmp/scope-e",
            "PORT": "3000",
            "SUMMARIZER_API_KEY": "dummy-secret-value",
        }

        with mock.patch.dict(os.environ, {}, clear=True):
            with mock.patch.object(config, "load_dotenv",
                                   lambda *a, **k: None):
                with mock.patch.object(config, "dotenv_values",
                                       return_value=dotenv):
                    loaded = config.load_viewer_config()

            self.assertIsNone(loaded.summarizer_api_key)
            self.assertNotIn("SUMMARIZER_API_KEY", os.environ)


class DeploymentUnitTest(unittest.TestCase):
    """ The viewer's systemd unit must not source the shared batch .env. """

    def setUp(self):
        path = os.path.join(REPO_ROOT, "deploy", "ai-digest.service")
        with open(path, encoding="utf-8") as handle:
            self.unit = handle.read()

    def test_does_not_source_the_shared_env_file(self):
        self.assertNotIn("EnvironmentFile", self.unit)

    def test_declares_data_dir_and_port_explicitly(self):
        self.assertRegex(self.unit, r"(?m)^Environment=DATA_DIR=")
        self.assertRegex(self.unit, r"(?m)^Environment=PORT=\d+$")

    def test_gunicorn_bind_shares_the_same_port_source(self):
        # A literal port number in ExecStart, independent of the
        # Environment=PORT= line above it, is the duplication this
        # guards against: the two would be free to drift apart.
        self.assertIn("${PORT}", self.unit)


if __name__ == "__main__":
    unittest.main()
