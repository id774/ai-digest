#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# config.py: Central configuration for ai-digest
#
#  Description:
#  This module collects every runtime setting of ai-digest in a single
#  place. All settings are read from environment variables (optionally
#  loaded from a local .env file) so that the same code base can run
#  unchanged on a workstation, a VPS or a PaaS such as Heroku.
#
#  The settings that address the summarization endpoint are named after
#  the stage that spends them, SUMMARIZER_*, and not after a vendor.
#  SUMMARIZER_BACKEND names a wire protocol rather than a company,
#  because 'anthropic-compatible' is spoken by endpoints that have
#  nothing to do with Anthropic, and the same key, base URL and model
#  reach whichever of them is configured. The former ANTHROPIC_* names
#  were also the ones the Anthropic SDK and other tools read from the
#  environment on their own, so a value exported for something else
#  decided where a digest was sent; they are refused by name now.
#
#  One endpoint answers at a time, so there is one set of credentials
#  rather than one per backend. SUMMARIZER_API_KEY and
#  SUMMARIZER_AUTH_TOKEN are two ways to authenticate the same request
#  and are mutually exclusive: on the anthropic-compatible backend they
#  select the x-api-key header or the Authorization Bearer header, and
#  on the openai-compatible backend both spell the Bearer header the
#  SDK sends either way.
#
#  The module exposes a single dataclass, Config, plus the helper
#  load_config() which builds a Config instance from os.environ. Nothing
#  in this module performs network access or touches the file system
#  beyond reading .env, so it is safe to import from anywhere.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - python-dotenv
#
#  Environment Variables:
#  - SUMMARIZER_BACKEND
#      Wire protocol of the summarization endpoint.
#      'anthropic-compatible' (default) speaks the Anthropic Messages
#      API for clustering, translation and classification.
#      'openai-compatible' speaks the OpenAI Chat Completions API
#      instead, for a provider whose Anthropic compatible endpoint
#      returns no usable tool call. 'plain' skips the API entirely and
#      builds topics mechanically, so the batch runs without a
#      credential at the cost of translation and clustering quality.
#      Any other value stops the batch instead of selecting a backend
#      that was not asked for.
#  - SUMMARIZER_API_KEY
#      API key of the summarization endpoint. Required by both API
#      backends unless SUMMARIZER_AUTH_TOKEN is set instead, unused by
#      SUMMARIZER_BACKEND=plain and unused by the Flask viewer in every
#      case.
#  - SUMMARIZER_AUTH_TOKEN
#      Bearer token of the summarization endpoint. Mutually exclusive
#      with SUMMARIZER_API_KEY.
#  - SUMMARIZER_BASE_URL
#      Base URL of the endpoint. Optional on the anthropic-compatible
#      backend, where an empty value means Anthropic itself. The
#      openai-compatible backend expects the version path to be part of
#      it, e.g. https://api.ai.sakura.ad.jp/v1, while the
#      anthropic-compatible one does not.
#  - SUMMARIZER_MODEL
#      Model asked for on the endpoint. Defaults to a Claude Sonnet
#      model on the anthropic-compatible backend; required on the
#      openai-compatible one, whose model names are the endpoint's own.
#  - SUMMARIZER_MAX_RETRIES
#      How often the SDK retries one request, on either API backend.
#      Defaults to 2, the SDK default; set 0 to spend exactly one
#      request per run, which is what comparing two endpoint settings
#      needs.
#  - SUMMARIZER_THINKING_MODE
#      Read by the anthropic-compatible backend. 'default' (default)
#      sends no thinking parameter and leaves the provider default in
#      place. 'disabled' asks the endpoint to turn the thinking output
#      off. Anthropic-compatible endpoints differ in how much they
#      think before answering, and a model that spends the whole output
#      budget on thinking never reaches the tool call.
#  - SUMMARIZER_TOOL_CHOICE_MODE
#      Read by the anthropic-compatible backend. 'forced' (default)
#      names build_report in tool_choice. 'any' demands a tool without
#      naming one. 'auto' lets the model pick the tool and disables
#      parallel tool use, for endpoints that do not honour a named
#      tool.
#  - SUMMARIZER_TEXT_JSON_FALLBACK
#      Read by the anthropic-compatible backend. 'disabled' (default)
#      accepts only a real tool call. 'enabled' also reads a report
#      written as JSON text, for an endpoint that produces the right
#      object but never wraps it in a tool_use block. It is off by
#      default because prose is easy to mistake for a report.
#  - ARXIV_CATEGORIES
#      Comma separated arXiv categories to collect (e.g. cs.AI,cs.LG).
#  - ARXIV_MAX_RESULTS
#      Upper bound of arXiv entries fetched per run.
#  - NEWS_FEED_URLS
#      Comma separated RSS/Atom feed URLs to collect.
#  - LOOKBACK_HOURS
#      Age limit, in hours, of collected entries.
#  - MAX_TOPICS
#      Maximum number of topics rendered in one daily report.
#  - MAX_OUTPUT_TOKENS
#      Tokens the model may produce in one answer, on either API
#      backend. Defaults to 8000, which fits the report with room to
#      spare. A model that thinks before answering draws on this same
#      budget, so an endpoint whose thinking cannot be turned off may
#      need more; raising it buys no tool call on its own.
#  - SUMMARIZER_TIMEOUT
#      Timeout, in seconds, of one summarization request, on either API
#      backend. Defaults to 180. It is separate from HTTP_TIMEOUT
#      because the two measure different things: a feed answers in
#      moments, while an answer of MAX_OUTPUT_TOKENS is written from
#      end to end before the client sees any of it.
#  - AI_DIGEST_FONT_PATH
#      Path of a CJK capable TrueType font used for image generation.
#  - DATA_DIR
#      Directory where generated reports are stored.
#  - HTTP_TIMEOUT
#      Timeout, in seconds, applied to every collector and scraper
#      request. The summarization request uses SUMMARIZER_TIMEOUT.
#  - USER_AGENT
#      User-Agent header sent with every outgoing HTTP request.
#  - PORT
#      TCP port used by the development server and by gunicorn.
#
#  Version History:
#  v1.4 2026-08-05
#       Name the endpoint settings after the summarization stage rather
#       than after a vendor: the ANTHROPIC_* and OPENAI_* variables
#       become one SUMMARIZER_* set, because one endpoint answers at a
#       time and neither prefix described what the value addressed. The
#       old names are refused at startup instead of being read, so that
#       an ANTHROPIC_BASE_URL exported for another tool cannot decide
#       where a digest is sent. SUMMARIZER_BACKEND now names the wire
#       protocol, 'anthropic-compatible' or 'openai-compatible', and
#       reports the replacement when it finds the former 'claude' or
#       'openai'.
#  v1.3 2026-08-05
#       Give the summarization request a timeout of its own,
#       SUMMARIZER_TIMEOUT, so that no outgoing request is left without
#       one. Raise the defaults of MAX_OUTPUT_TOKENS to 8000 and
#       HTTP_TIMEOUT to 60, and move the viewer to port 3000.
#  v1.2 2026-08-04
#       Expose the comma separated list parser as split_csv(), so that
#       the command line reads a list exactly as the environment does.
#       Fall back on the default User-Agent when USER_AGENT is set but
#       empty, as every other string setting already does.
#  v1.1 2026-08-02
#       Reject an unknown SUMMARIZER_BACKEND instead of falling back on
#       the default, and drop the unused require_api_key(). Add
#       ANTHROPIC_THINKING_MODE, ANTHROPIC_TOOL_CHOICE_MODE with its
#       'any' value, ANTHROPIC_TEXT_JSON_FALLBACK and
#       ANTHROPIC_MAX_RETRIES, so that the request an
#       Anthropic-compatible endpoint receives can be set explicitly.
#       Add the OpenAI compatible backend with its key, base URL and
#       model, and read MAX_OUTPUT_TOKENS from the environment instead
#       of leaving it to the summarizer constant.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import os
from dataclasses import dataclass, field
from typing import List, Optional

try:
    from dotenv import load_dotenv
except ImportError:  # python-dotenv is optional at import time
    load_dotenv = None

# Directory holding this file, used to resolve default relative paths.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# Valid values of SUMMARIZER_BACKEND. The two API backends name a wire
# protocol rather than the company that first published it, because
# either one is spoken by endpoints belonging to neither. 'plain'
# builds topics mechanically and needs no credential.
SUMMARIZER_BACKENDS = ("anthropic-compatible", "openai-compatible", "plain")

# Valid values of SUMMARIZER_THINKING_MODE. 'default' keeps the provider
# default; 'disabled' asks the endpoint to answer without thinking.
SUMMARIZER_THINKING_MODES = ("default", "disabled")

# Valid values of SUMMARIZER_TOOL_CHOICE_MODE. 'forced' names the tool
# to call; 'any' demands some tool without naming it, which is
# unambiguous here because build_report is the only one offered; 'auto'
# leaves the choice to the model.
SUMMARIZER_TOOL_CHOICE_MODES = ("forced", "any", "auto")

# Valid values of SUMMARIZER_TEXT_JSON_FALLBACK. 'disabled' accepts only
# a real tool call; 'enabled' also reads a JSON report written as text.
SUMMARIZER_TEXT_JSON_FALLBACK_MODES = ("disabled", "enabled")

# Model used when SUMMARIZER_MODEL is unset and the backend speaks the
# Anthropic protocol. The openai-compatible backend ships no default,
# because the models an endpoint offers are its own.
DEFAULT_ANTHROPIC_MODEL = "claude-sonnet-4-5"

# The settings these replaced, and the name that replaced each. They are
# refused rather than read, because ANTHROPIC_API_KEY, ANTHROPIC_BASE_URL
# and ANTHROPIC_AUTH_TOKEN are also what the Anthropic SDK and other
# tools take from the environment on their own: a value exported for one
# of those would otherwise send a nightly digest to an endpoint nobody
# chose here, and a stale OPENAI_MODEL would name a model on an endpoint
# that never heard of it.
LEGACY_VARIABLES = {
    "ANTHROPIC_API_KEY": "SUMMARIZER_API_KEY",
    "ANTHROPIC_AUTH_TOKEN": "SUMMARIZER_AUTH_TOKEN",
    "ANTHROPIC_BASE_URL": "SUMMARIZER_BASE_URL",
    "ANTHROPIC_MODEL": "SUMMARIZER_MODEL",
    "ANTHROPIC_THINKING_MODE": "SUMMARIZER_THINKING_MODE",
    "ANTHROPIC_TOOL_CHOICE_MODE": "SUMMARIZER_TOOL_CHOICE_MODE",
    "ANTHROPIC_TEXT_JSON_FALLBACK": "SUMMARIZER_TEXT_JSON_FALLBACK",
    "ANTHROPIC_MAX_RETRIES": "SUMMARIZER_MAX_RETRIES",
    "OPENAI_API_KEY": "SUMMARIZER_API_KEY",
    "OPENAI_BASE_URL": "SUMMARIZER_BASE_URL",
    "OPENAI_MODEL": "SUMMARIZER_MODEL",
}

# The SUMMARIZER_BACKEND values these replaced. A run that still asks
# for one is stopped by name rather than by the generic message, so
# that an upgrade reads its own answer instead of guessing which of the
# three new values the old one became.
LEGACY_BACKENDS = {
    "claude": "anthropic-compatible",
    "openai": "openai-compatible",
}

# Default arXiv categories: artificial intelligence, machine learning
# and computation and language.
DEFAULT_ARXIV_CATEGORIES = "cs.AI,cs.LG,cs.CL"

# Identity sent to arXiv and to the feed and publisher hosts. It names
# the project so that an operator reading their logs can tell who is
# calling and where to complain.
DEFAULT_USER_AGENT = "ai-digest/1.0 (+https://github.com/id774/ai-digest)"

# Default news feeds. They are deliberately few and stable; extend the
# list through NEWS_FEED_URLS instead of editing this constant.
DEFAULT_NEWS_FEED_URLS = ",".join([
    "https://openai.com/news/rss.xml",
    "https://blog.google/technology/ai/rss/",
    "https://huggingface.co/blog/feed.xml",
])

# Font paths probed when AI_DIGEST_FONT_PATH is not set. Only fonts with
# CJK glyphs are listed, because every rendered string is Japanese.
CJK_FONT_CANDIDATES = (
    "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    "/usr/share/fonts/opentype/noto/NotoSansCJKjp-Regular.otf",
    "/usr/share/fonts/truetype/fonts-japanese-gothic.ttf",
    "/usr/share/fonts/truetype/vlgothic/VL-Gothic-Regular.ttf",
    "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
    "C:\\Windows\\Fonts\\meiryo.ttc",
    "C:\\Windows\\Fonts\\msgothic.ttc",
)


def split_csv(value: str) -> List[str]:
    """
    Split a comma separated setting into a clean list.

    Shared with the command line parser, so that a list given as an
    option is read exactly like the same list given in the environment.
    """
    return [item.strip() for item in value.split(",") if item.strip()]


def _env_int(name: str, default: int) -> int:
    """ Read an integer environment variable, falling back on default. """
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


def _env_token(name: str, default: str) -> str:
    """
    Read a lower case token environment variable.

    An unset or empty variable yields the default. Any other value is
    returned as it was configured, even when it is not a value the
    application knows: silently replacing it with the default is how a
    typo turns into a run that behaves nothing like the one intended.
    Validation belongs to the caller, which can report the bad value.
    """
    raw = os.environ.get(name, "").strip().lower()
    return raw or default


def detect_font_path(explicit: Optional[str] = None) -> Optional[str]:
    """
    Return a usable CJK font path.

    The explicit argument wins when it points at an existing file.
    Otherwise the well known locations in CJK_FONT_CANDIDATES are
    probed. None is returned when no CJK font is installed, in which
    case the image generators fall back to the bitmap font bundled with
    Pillow and Japanese characters render as blank boxes.
    """
    if explicit and os.path.isfile(explicit):
        return explicit
    for candidate in CJK_FONT_CANDIDATES:
        if os.path.isfile(candidate):
            return candidate
    return None


@dataclass
class Config:
    """ Immutable snapshot of every runtime setting. """

    summarizer_api_key: Optional[str] = None
    summarizer_auth_token: Optional[str] = None
    summarizer_base_url: Optional[str] = None
    summarizer_model: str = ""
    summarizer_thinking_mode: str = "default"
    summarizer_tool_choice_mode: str = "forced"
    summarizer_text_json_fallback: str = "disabled"
    summarizer_max_retries: int = 2
    max_output_tokens: int = 8000
    summarizer_timeout: int = 180
    summarizer_backend: str = "anthropic-compatible"
    arxiv_categories: List[str] = field(default_factory=list)
    arxiv_max_results: int = 60
    news_feed_urls: List[str] = field(default_factory=list)
    lookback_hours: int = 24
    max_topics: int = 6
    font_path: Optional[str] = None
    data_dir: str = os.path.join(BASE_DIR, "data", "reports")
    http_timeout: int = 60
    user_agent: str = DEFAULT_USER_AGENT
    port: int = 3000

    @property
    def resolved_model(self) -> str:
        """
        Return the model to ask for, or an empty string when none is set.

        The anthropic-compatible backend falls back on a known Claude
        model, which is what an unconfigured SUMMARIZER_MODEL means when
        the endpoint is Anthropic itself. The openai-compatible backend
        has nothing to fall back on, so the empty string travels to
        validate_summarizer_model(), which refuses the run by name.
        """
        if self.summarizer_model:
            return self.summarizer_model
        if self.summarizer_backend == "anthropic-compatible":
            return DEFAULT_ANTHROPIC_MODEL
        return ""

    def validate_summarizer_backend(self) -> None:
        """
        Raise when SUMMARIZER_BACKEND names an unknown backend.

        The batch calls this before anything else. Falling back on the
        default instead would send a run meant to stay offline through
        an API, spending requests on a typo, so an unrecognized value
        stops the run and names itself. A value this project used to
        accept is answered with the name that replaced it, because the
        generic list does not say which of the three it became.
        """
        if self.summarizer_backend in LEGACY_BACKENDS:
            raise RuntimeError(
                "SUMMARIZER_BACKEND is '{0}', which named a vendor rather "
                "than a wire protocol; use '{1}'.".format(
                    self.summarizer_backend,
                    LEGACY_BACKENDS[self.summarizer_backend],
                )
            )
        if self.summarizer_backend not in SUMMARIZER_BACKENDS:
            raise RuntimeError(
                "SUMMARIZER_BACKEND is '{0}'; expected one of: {1}.".format(
                    self.summarizer_backend, ", ".join(SUMMARIZER_BACKENDS)
                )
            )

    def validate_summarizer_auth(self) -> None:
        """
        Validate the credential of the summarization endpoint.

        The two variables are two ways to authenticate one request, so
        setting both states two intentions and neither wins on merit.
        Which header each becomes is the backend's business: the
        anthropic-compatible one sends x-api-key or Authorization,
        while the openai-compatible one sends Authorization either way.
        """
        if self.summarizer_api_key and self.summarizer_auth_token:
            raise RuntimeError(
                "Set only one of SUMMARIZER_API_KEY and SUMMARIZER_AUTH_TOKEN."
            )
        if not self.summarizer_api_key and not self.summarizer_auth_token:
            raise RuntimeError(
                "SUMMARIZER_API_KEY or SUMMARIZER_AUTH_TOKEN is required. "
                "Export one or place it in .env."
            )

    def validate_summarizer_model(self) -> None:
        """
        Raise when no model can be named for the selected backend.

        Only the openai-compatible backend can reach this, because the
        anthropic-compatible one resolves to DEFAULT_ANTHROPIC_MODEL.
        """
        if not self.resolved_model:
            raise RuntimeError(
                "SUMMARIZER_MODEL is required by "
                "SUMMARIZER_BACKEND={0}.".format(self.summarizer_backend)
            )

    def validate_retry_budget(self) -> None:
        """
        Raise when SUMMARIZER_MAX_RETRIES cannot bound a request.

        Both API backends hand this to their SDK, and a negative value
        is rejected there after everything is collected.
        """
        if self.summarizer_max_retries < 0:
            raise RuntimeError(
                "SUMMARIZER_MAX_RETRIES is {0}; expected zero or "
                "more.".format(self.summarizer_max_retries)
            )

    def validate_protocol_options(self) -> None:
        """
        Raise when a thinking or tool choice value is unknown.

        These settings decide what the anthropic-compatible request
        looks like, so a typo would silently send the default request to
        an endpoint that needs the other one, and the run would fail
        much later with a message about a missing tool call.
        """
        if self.summarizer_thinking_mode not in SUMMARIZER_THINKING_MODES:
            raise RuntimeError(
                "SUMMARIZER_THINKING_MODE is '{0}'; expected one of: "
                "{1}.".format(
                    self.summarizer_thinking_mode,
                    ", ".join(SUMMARIZER_THINKING_MODES),
                )
            )
        if (self.summarizer_tool_choice_mode
                not in SUMMARIZER_TOOL_CHOICE_MODES):
            raise RuntimeError(
                "SUMMARIZER_TOOL_CHOICE_MODE is '{0}'; expected one of: "
                "{1}.".format(
                    self.summarizer_tool_choice_mode,
                    ", ".join(SUMMARIZER_TOOL_CHOICE_MODES),
                )
            )
        if (self.summarizer_text_json_fallback
                not in SUMMARIZER_TEXT_JSON_FALLBACK_MODES):
            raise RuntimeError(
                "SUMMARIZER_TEXT_JSON_FALLBACK is '{0}'; expected one of: "
                "{1}.".format(
                    self.summarizer_text_json_fallback,
                    ", ".join(SUMMARIZER_TEXT_JSON_FALLBACK_MODES),
                )
            )

    def validate_output_budget(self) -> None:
        """
        Raise when MAX_OUTPUT_TOKENS cannot shape a request.

        Both API backends spend this budget, and the message a
        truncated report prints tells the reader to raise it, so the
        value has to be usable before a run starts rather than be
        rejected by the endpoint after everything is collected.
        """
        if self.max_output_tokens < 1:
            raise RuntimeError(
                "MAX_OUTPUT_TOKENS is {0}; expected a positive number.".format(
                    self.max_output_tokens
                )
            )

    def validate_summarizer_timeout(self) -> None:
        """
        Raise when SUMMARIZER_TIMEOUT cannot bound a request.

        A run that starts with a timeout of zero or less would either be
        refused by the SDK after everything is collected, or fall back
        on a default measured in minutes. An unattended run must not
        hang until the next one starts, so the value is checked before
        the first source is read.
        """
        if self.summarizer_timeout < 1:
            raise RuntimeError(
                "SUMMARIZER_TIMEOUT is {0}; expected a positive number "
                "of seconds.".format(self.summarizer_timeout)
            )


def _refuse_legacy_variables() -> None:
    """
    Refuse a superseded setting instead of reading it as its successor.

    Presence is what is refused, not the value: an exported but empty
    ANTHROPIC_BASE_URL still says the host was configured for the old
    names, and reading the new ones alongside it would leave the
    operator with a run that ignores half of what they wrote.
    """
    for name in sorted(LEGACY_VARIABLES):
        if name in os.environ:
            raise RuntimeError(
                "{0} is no longer read by ai-digest; use {1}.".format(
                    name, LEGACY_VARIABLES[name]
                )
            )


def load_config() -> Config:
    """
    Build a Config from environment variables.

    A .env file in the repository root is loaded first when
    python-dotenv is installed. Existing environment variables always
    take precedence over .env entries.

    A superseded variable stops the load, after .env is read so that a
    stale line in the file is caught as well as a stale export.
    """
    if load_dotenv is not None:
        load_dotenv(os.path.join(BASE_DIR, ".env"))

    _refuse_legacy_variables()

    data_dir = os.environ.get("DATA_DIR", "").strip()
    if not data_dir:
        data_dir = os.path.join(BASE_DIR, "data", "reports")

    return Config(
        summarizer_api_key=os.environ.get("SUMMARIZER_API_KEY") or None,
        summarizer_auth_token=os.environ.get("SUMMARIZER_AUTH_TOKEN") or None,
        summarizer_base_url=os.environ.get("SUMMARIZER_BASE_URL") or None,
        summarizer_model=os.environ.get("SUMMARIZER_MODEL", "").strip(),
        summarizer_thinking_mode=_env_token(
            "SUMMARIZER_THINKING_MODE", "default"
        ),
        summarizer_tool_choice_mode=_env_token(
            "SUMMARIZER_TOOL_CHOICE_MODE", "forced"
        ),
        summarizer_text_json_fallback=_env_token(
            "SUMMARIZER_TEXT_JSON_FALLBACK", "disabled"
        ),
        summarizer_max_retries=_env_int("SUMMARIZER_MAX_RETRIES", 2),
        max_output_tokens=_env_int("MAX_OUTPUT_TOKENS", 8000),
        summarizer_timeout=_env_int("SUMMARIZER_TIMEOUT", 180),
        summarizer_backend=_env_token(
            "SUMMARIZER_BACKEND", "anthropic-compatible"
        ),
        arxiv_categories=split_csv(
            os.environ.get("ARXIV_CATEGORIES", DEFAULT_ARXIV_CATEGORIES)
        ),
        arxiv_max_results=_env_int("ARXIV_MAX_RESULTS", 60),
        news_feed_urls=split_csv(
            os.environ.get("NEWS_FEED_URLS", DEFAULT_NEWS_FEED_URLS)
        ),
        lookback_hours=_env_int("LOOKBACK_HOURS", 24),
        max_topics=_env_int("MAX_TOPICS", 6),
        font_path=detect_font_path(os.environ.get("AI_DIGEST_FONT_PATH")),
        data_dir=os.path.abspath(data_dir),
        http_timeout=_env_int("HTTP_TIMEOUT", 60),
        user_agent=(os.environ.get("USER_AGENT", "").strip()
                    or DEFAULT_USER_AGENT),
        port=_env_int("PORT", 3000),
    )
