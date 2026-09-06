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
#  The base URL cases cover validate_summarizer_base_url(): a missing,
#  empty or whitespace-only value is refused on the openai-compatible
#  protocol, because it used to fall through to the OpenAI SDK's own
#  default endpoint, while the anthropic-compatible and plain backends
#  keep accepting no base URL at all, which is not a defect for either.
#
#  The numeric setting cases cover every integer setting alike, table
#  driven: unset and blank both read as the default, an explicit value
#  that is not a whole number is a configuration error rather than a
#  silent fallback to the default, and the same holds for a value
#  outside the setting's range. SUMMARIZER_MAX_RETRIES accepts zero; the
#  other seven do not.
#
#  The font cases cover the same distinction for AI_DIGEST_FONT_PATH:
#  unset or blank probes CJK_FONT_CANDIDATES for the first Pillow can
#  actually load, skipping one it cannot, while a nonblank value is an
#  explicit request that is used exactly or refused, never silently
#  replaced by a probed candidate. The Pillow load itself is mocked
#  throughout, so no case depends on a font installed on the host.
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
#    - Reject a missing, an empty and a whitespace-only base URL on the
#      OpenAI protocol.
#    - Accept an explicit base URL on the OpenAI protocol.
#    - Keep accepting a missing base URL on the Anthropic protocol and
#      on plain.
#    - Use the default for every numeric setting when it is unset or blank.
#    - Reject an explicit numeric setting that is not a whole number.
#    - Keep a valid explicit numeric setting.
#    - Accept a retry budget of zero, and reject a negative one.
#    - Reject zero and a negative value for the other numeric settings.
#    - Judge font usability by existence and by Pillow loadability alike.
#    - Probe automatic font candidates in order, skipping an unusable one.
#    - Resolve an unset or blank font setting automatically, and refuse
#      an unusable explicit one without probing a candidate.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Pillow
#
#  Version History:
#  v1.1 2026-09-06
#       Resolve font paths per execution scope; explicit invalid values fail.
#  v1.0 2026-08-05
#       Initial release.
#
########################################################################

import os
import tempfile
import unittest
from dataclasses import replace
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


class SummarizerBaseUrlTest(unittest.TestCase):
    """
    validate_summarizer_base_url() must keep the openai-compatible
    backend from reaching the SDK with no endpoint target of its own,
    without touching the anthropic-compatible or plain backends, where
    an unset base URL is not a defect.
    """

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_rejects_a_missing_base_url_on_the_openai_protocol(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible"})

        self.assertIsNone(loaded.summarizer_base_url)
        with self.assertRaisesRegex(
                RuntimeError,
                "SUMMARIZER_BASE_URL.*SUMMARIZER_BACKEND=openai-compatible"):
            loaded.validate_summarizer_base_url()

    def test_rejects_an_empty_base_url_on_the_openai_protocol(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible",
                            "SUMMARIZER_BASE_URL": ""})

        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_BASE_URL"):
            loaded.validate_summarizer_base_url()

    def test_rejects_a_whitespace_only_base_url_on_the_openai_protocol(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible"})
        loaded = replace(loaded, summarizer_base_url="   ")

        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_BASE_URL"):
            loaded.validate_summarizer_base_url()

    def test_accepts_an_explicit_base_url_on_the_openai_protocol(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "openai-compatible",
                            "SUMMARIZER_BASE_URL":
                                "https://api.example.test/v1"})

        loaded.validate_summarizer_base_url()

    def test_a_missing_base_url_still_passes_on_the_anthropic_protocol(self):
        loaded = self.load({})

        self.assertIsNone(loaded.summarizer_base_url)
        loaded.validate_summarizer_base_url()

    def test_a_missing_base_url_still_passes_on_plain(self):
        loaded = self.load({"SUMMARIZER_BACKEND": "plain"})

        loaded.validate_summarizer_base_url()


# (env var name, Config field, default, minimum) for every integer setting.
NUMERIC_SETTINGS = (
    ("SUMMARIZER_MAX_RETRIES", "summarizer_max_retries", 2, 0),
    ("MAX_OUTPUT_TOKENS", "max_output_tokens", 8000, 1),
    ("SUMMARIZER_TIMEOUT", "summarizer_timeout", 180, 1),
    ("ARXIV_MAX_RESULTS", "arxiv_max_results", 60, 1),
    ("LOOKBACK_HOURS", "lookback_hours", 24, 1),
    ("MAX_TOPICS", "max_topics", 6, 1),
    ("HTTP_TIMEOUT", "http_timeout", 60, 1),
    ("PORT", "port", 3000, 1),
)


class NumericSettingTest(unittest.TestCase):
    """
    Every integer setting reads unset and blank alike as its default,
    and refuses an explicit value that is not a whole number or that
    falls outside its range, instead of silently keeping the default.
    """

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_uses_the_default_when_unset(self):
        for name, field, default, _minimum in NUMERIC_SETTINGS:
            with self.subTest(name=name):
                self.assertEqual(default, getattr(self.load({}), field))

    def test_uses_the_default_when_blank(self):
        for name, field, default, _minimum in NUMERIC_SETTINGS:
            with self.subTest(name=name):
                loaded = self.load({name: "   "})
                self.assertEqual(default, getattr(loaded, field))

    def test_rejects_a_non_integer_value(self):
        for name, _field, _default, _minimum in NUMERIC_SETTINGS:
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, name):
                    self.load({name: "not-a-number"})

    def test_keeps_a_valid_explicit_value(self):
        for name, field, default, _minimum in NUMERIC_SETTINGS:
            with self.subTest(name=name):
                value = default + 1
                loaded = self.load({name: str(value)})
                self.assertEqual(value, getattr(loaded, field))

    def test_retries_accepts_zero(self):
        loaded = self.load({"SUMMARIZER_MAX_RETRIES": "0"})

        self.assertEqual(0, loaded.summarizer_max_retries)

    def test_retries_rejects_a_negative_value(self):
        with self.assertRaisesRegex(RuntimeError, "SUMMARIZER_MAX_RETRIES"):
            self.load({"SUMMARIZER_MAX_RETRIES": "-1"})

    def test_the_other_settings_reject_zero(self):
        for name, _field, _default, minimum in NUMERIC_SETTINGS:
            if minimum == 0:
                continue
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, name):
                    self.load({name: "0"})

    def test_the_other_settings_reject_a_negative_value(self):
        for name, _field, _default, minimum in NUMERIC_SETTINGS:
            if minimum == 0:
                continue
            with self.subTest(name=name):
                with self.assertRaisesRegex(RuntimeError, name):
                    self.load({name: "-1"})


class FontUsabilityTest(unittest.TestCase):
    """
    is_usable_font_path() is the one place that decides whether a font
    file is usable, for an automatic candidate, an explicit setting and
    the CLI option alike. The Pillow load itself is mocked, so no case
    here depends on a font actually installed on the host.
    """

    def test_a_missing_path_is_unusable(self):
        self.assertFalse(config.is_usable_font_path("/no/such/font.ttf"))

    def test_a_directory_is_unusable(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertFalse(config.is_usable_font_path(directory))

    def test_an_existing_file_pillow_can_load_is_usable(self):
        with tempfile.NamedTemporaryFile(suffix=".ttf") as handle:
            with mock.patch.object(config.ImageFont, "truetype") as truetype:
                self.assertTrue(config.is_usable_font_path(handle.name))
            truetype.assert_called_once()

    def test_an_existing_file_pillow_cannot_load_is_unusable(self):
        with tempfile.NamedTemporaryFile(suffix=".ttf") as handle:
            with mock.patch.object(config.ImageFont, "truetype",
                                   side_effect=OSError("not a font")):
                self.assertFalse(config.is_usable_font_path(handle.name))


class AutomaticFontDetectionTest(unittest.TestCase):
    """ detect_font_path() probes CJK_FONT_CANDIDATES for automatic mode. """

    def test_selects_the_first_usable_candidate(self):
        with mock.patch.object(config, "CJK_FONT_CANDIDATES",
                              ("a", "b", "c")):
            with mock.patch.object(config, "is_usable_font_path",
                                   side_effect=lambda path: path == "b"):
                self.assertEqual("b", config.detect_font_path())

    def test_probes_candidates_in_the_existing_order(self):
        probed = []

        def record(path):
            probed.append(path)
            return False

        with mock.patch.object(config, "CJK_FONT_CANDIDATES",
                              ("a", "b", "c")):
            with mock.patch.object(config, "is_usable_font_path",
                                   side_effect=record):
                config.detect_font_path()

        self.assertEqual(["a", "b", "c"], probed)

    def test_none_when_no_candidate_is_usable(self):
        with mock.patch.object(config, "CJK_FONT_CANDIDATES", ("a", "b")):
            with mock.patch.object(config, "is_usable_font_path",
                                   return_value=False):
                self.assertIsNone(config.detect_font_path())


class ExplicitFontPathTest(unittest.TestCase):
    """
    resolve_font_path() is what an environment or .env value goes
    through: automatic detection when unset or blank, and a strict,
    non-repaired check of the exact path otherwise.
    """

    def test_none_uses_automatic_detection(self):
        with mock.patch.object(config, "detect_font_path",
                               return_value="/auto/font.ttf") as detect:
            self.assertEqual("/auto/font.ttf", config.resolve_font_path(None))

        detect.assert_called_once()

    def test_blank_and_whitespace_only_use_automatic_detection(self):
        with mock.patch.object(config, "detect_font_path",
                               return_value="/auto/font.ttf") as detect:
            self.assertEqual("/auto/font.ttf", config.resolve_font_path(""))
            self.assertEqual("/auto/font.ttf",
                            config.resolve_font_path("   "))

        self.assertEqual(2, detect.call_count)

    def test_a_valid_explicit_path_is_used_exactly(self):
        with mock.patch.object(config, "is_usable_font_path",
                               return_value=True):
            self.assertEqual("/explicit/font.ttf",
                            config.resolve_font_path("/explicit/font.ttf"))

    def test_an_invalid_explicit_path_is_refused_without_probing(self):
        with mock.patch.object(config, "is_usable_font_path",
                               return_value=False):
            with mock.patch.object(config, "detect_font_path") as detect:
                with self.assertRaisesRegex(RuntimeError,
                                            "AI_DIGEST_FONT_PATH"):
                    config.resolve_font_path("/bad/font.ttf")

        detect.assert_not_called()


class FontPathConfigurationTest(unittest.TestCase):
    """ AI_DIGEST_FONT_PATH resolved end to end through load_config(). """

    def load(self, environment):
        with mock.patch.dict(os.environ, environment, clear=True):
            with mock.patch.object(config, "load_dotenv", None):
                return config.load_config()

    def test_unset_font_path_uses_automatic_detection(self):
        with mock.patch.object(config, "detect_font_path",
                               return_value="/auto/font.ttf") as detect:
            loaded = self.load({})

        self.assertEqual("/auto/font.ttf", loaded.font_path)
        detect.assert_called_once()

    def test_valid_explicit_font_path_is_used_exactly(self):
        with mock.patch.object(config, "is_usable_font_path",
                               return_value=True):
            loaded = self.load({"AI_DIGEST_FONT_PATH": "/explicit/font.ttf"})

        self.assertEqual("/explicit/font.ttf", loaded.font_path)

    def test_invalid_explicit_font_path_fails_the_load(self):
        with mock.patch.object(config, "is_usable_font_path",
                               return_value=False):
            with self.assertRaisesRegex(RuntimeError, "AI_DIGEST_FONT_PATH"):
                self.load({"AI_DIGEST_FONT_PATH": "/bad/font.ttf"})


if __name__ == "__main__":
    unittest.main()
