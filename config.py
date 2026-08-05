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
#  - ANTHROPIC_API_KEY
#      API key for the Claude API. Required by the batch pipeline when
#      SUMMARIZER_BACKEND is 'claude' (the default), unused otherwise
#      and unused by the Flask viewer in every case.
#  - ANTHROPIC_AUTH_TOKEN
#      Bearer token for an Anthropic-compatible API. Mutually exclusive
#      with ANTHROPIC_API_KEY.
#  - ANTHROPIC_BASE_URL
#      Optional base URL for an Anthropic-compatible API.
#  - ANTHROPIC_MODEL
#      Model name used for summarization. Defaults to a Claude Sonnet
#      model; override it when a different model is preferred.
#  - ANTHROPIC_THINKING_MODE
#      'default' (default) sends no thinking parameter and leaves the
#      provider default in place. 'disabled' asks the endpoint to turn
#      the thinking output off. Anthropic-compatible endpoints differ in
#      how much they think before answering, and a model that spends the
#      whole output budget on thinking never reaches the tool call.
#  - ANTHROPIC_TOOL_CHOICE_MODE
#      'forced' (default) names build_report in tool_choice. 'auto' lets
#      the model pick the tool and disables parallel tool use, for
#      endpoints that do not honour a named tool.
#  - ANTHROPIC_TEXT_JSON_FALLBACK
#      'disabled' (default) accepts only a real tool call. 'enabled'
#      also reads a report written as JSON text, for an endpoint that
#      produces the right object but never wraps it in a tool_use
#      block. It is off by default because prose is easy to mistake for
#      a report.
#  - ANTHROPIC_MAX_RETRIES
#      How often the Anthropic SDK retries one request. Defaults to 2,
#      the SDK default; set 0 to spend exactly one request per run,
#      which is what comparing two endpoint settings needs.
#  - OPENAI_API_KEY
#      Key of the OpenAI compatible endpoint. Required by
#      SUMMARIZER_BACKEND=openai and unused otherwise.
#  - OPENAI_BASE_URL
#      Base URL of the OpenAI compatible endpoint, including the
#      version path, e.g. https://api.ai.sakura.ad.jp/v1.
#  - OPENAI_MODEL
#      Model asked for on that endpoint. Required by
#      SUMMARIZER_BACKEND=openai; it has no sensible default.
#  - SUMMARIZER_BACKEND
#      'claude' (default) calls the Claude API for clustering,
#      translation and classification. 'plain' skips the API entirely
#      and builds topics mechanically, so the batch can run without
#      ANTHROPIC_API_KEY at the cost of translation and clustering
#      quality. 'openai' calls an OpenAI compatible Chat Completions
#      API instead, for a provider whose Anthropic compatible endpoint
#      returns no usable tool call. Any other value stops the batch
#      instead of selecting a backend that was not asked for.
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

# Valid values of SUMMARIZER_BACKEND. 'claude' calls the Claude API;
# 'plain' builds topics mechanically and needs no API key; 'openai'
# calls an OpenAI compatible Chat Completions API, for a provider whose
# Anthropic compatible endpoint returns no usable tool call.
SUMMARIZER_BACKENDS = ("claude", "plain", "openai")

# Valid values of ANTHROPIC_THINKING_MODE. 'default' keeps the provider
# default; 'disabled' asks the endpoint to answer without thinking.
ANTHROPIC_THINKING_MODES = ("default", "disabled")

# Valid values of ANTHROPIC_TOOL_CHOICE_MODE. 'forced' names the tool to
# call; 'any' demands some tool without naming it, which is unambiguous
# here because build_report is the only one offered; 'auto' leaves the
# choice to the model.
ANTHROPIC_TOOL_CHOICE_MODES = ("forced", "any", "auto")

# Valid values of ANTHROPIC_TEXT_JSON_FALLBACK. 'disabled' accepts only
# a real tool call; 'enabled' also reads a JSON report written as text.
ANTHROPIC_TEXT_JSON_FALLBACK_MODES = ("disabled", "enabled")

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

    anthropic_api_key: Optional[str] = None
    anthropic_auth_token: Optional[str] = None
    anthropic_base_url: Optional[str] = None
    anthropic_model: str = "claude-sonnet-4-5"
    anthropic_thinking_mode: str = "default"
    anthropic_tool_choice_mode: str = "forced"
    anthropic_text_json_fallback: str = "disabled"
    anthropic_max_retries: int = 2
    max_output_tokens: int = 8000
    summarizer_timeout: int = 180
    openai_api_key: Optional[str] = None
    openai_base_url: Optional[str] = None
    openai_model: str = ""
    summarizer_backend: str = "claude"
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

    def validate_summarizer_backend(self) -> None:
        """
        Raise when SUMMARIZER_BACKEND names an unknown backend.

        The batch calls this before anything else. Falling back on the
        default instead would send a run meant to stay offline through
        the Claude API, spending API calls on a typo, so an
        unrecognized value stops the run and names itself.
        """
        if self.summarizer_backend not in SUMMARIZER_BACKENDS:
            raise RuntimeError(
                "SUMMARIZER_BACKEND is '{0}'; expected one of: {1}.".format(
                    self.summarizer_backend, ", ".join(SUMMARIZER_BACKENDS)
                )
            )

    def validate_anthropic_auth(self) -> None:
        """ Validate the configured Anthropic-compatible authentication. """
        if self.anthropic_api_key and self.anthropic_auth_token:
            raise RuntimeError(
                "Set only one of ANTHROPIC_API_KEY and ANTHROPIC_AUTH_TOKEN."
            )
        if not self.anthropic_api_key and not self.anthropic_auth_token:
            raise RuntimeError(
                "ANTHROPIC_API_KEY or ANTHROPIC_AUTH_TOKEN is required. "
                "Export one or place it in .env."
            )

    def validate_anthropic_options(self) -> None:
        """
        Raise when a thinking or tool choice value is unknown.

        These two settings decide what the request looks like, so a typo
        would silently send the default request to an endpoint that
        needs the other one, and the run would fail much later with a
        message about a missing tool call.
        """
        if self.anthropic_thinking_mode not in ANTHROPIC_THINKING_MODES:
            raise RuntimeError(
                "ANTHROPIC_THINKING_MODE is '{0}'; expected one of: "
                "{1}.".format(
                    self.anthropic_thinking_mode,
                    ", ".join(ANTHROPIC_THINKING_MODES),
                )
            )
        if self.anthropic_tool_choice_mode not in ANTHROPIC_TOOL_CHOICE_MODES:
            raise RuntimeError(
                "ANTHROPIC_TOOL_CHOICE_MODE is '{0}'; expected one of: "
                "{1}.".format(
                    self.anthropic_tool_choice_mode,
                    ", ".join(ANTHROPIC_TOOL_CHOICE_MODES),
                )
            )
        if (self.anthropic_text_json_fallback
                not in ANTHROPIC_TEXT_JSON_FALLBACK_MODES):
            raise RuntimeError(
                "ANTHROPIC_TEXT_JSON_FALLBACK is '{0}'; expected one of: "
                "{1}.".format(
                    self.anthropic_text_json_fallback,
                    ", ".join(ANTHROPIC_TEXT_JSON_FALLBACK_MODES),
                )
            )
        if self.anthropic_max_retries < 0:
            raise RuntimeError(
                "ANTHROPIC_MAX_RETRIES is {0}; expected zero or more.".format(
                    self.anthropic_max_retries
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

    def validate_openai_options(self) -> None:
        """
        Raise when the OpenAI compatible backend is not configured.

        The key and the model have no usable default: the backend exists
        for third party endpoints, whose model names are their own.
        """
        if not self.openai_api_key:
            raise RuntimeError(
                "OPENAI_API_KEY is required by SUMMARIZER_BACKEND=openai. "
                "Export it or place it in .env."
            )
        if not self.openai_model:
            raise RuntimeError(
                "OPENAI_MODEL is required by SUMMARIZER_BACKEND=openai."
            )


def load_config() -> Config:
    """
    Build a Config from environment variables.

    A .env file in the repository root is loaded first when
    python-dotenv is installed. Existing environment variables always
    take precedence over .env entries.
    """
    if load_dotenv is not None:
        load_dotenv(os.path.join(BASE_DIR, ".env"))

    data_dir = os.environ.get("DATA_DIR", "").strip()
    if not data_dir:
        data_dir = os.path.join(BASE_DIR, "data", "reports")

    return Config(
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY") or None,
        anthropic_auth_token=os.environ.get("ANTHROPIC_AUTH_TOKEN") or None,
        anthropic_base_url=os.environ.get("ANTHROPIC_BASE_URL") or None,
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5").strip()
        or "claude-sonnet-4-5",
        anthropic_thinking_mode=_env_token(
            "ANTHROPIC_THINKING_MODE", "default"
        ),
        anthropic_tool_choice_mode=_env_token(
            "ANTHROPIC_TOOL_CHOICE_MODE", "forced"
        ),
        anthropic_text_json_fallback=_env_token(
            "ANTHROPIC_TEXT_JSON_FALLBACK", "disabled"
        ),
        anthropic_max_retries=_env_int("ANTHROPIC_MAX_RETRIES", 2),
        max_output_tokens=_env_int("MAX_OUTPUT_TOKENS", 8000),
        summarizer_timeout=_env_int("SUMMARIZER_TIMEOUT", 180),
        openai_api_key=os.environ.get("OPENAI_API_KEY") or None,
        openai_base_url=os.environ.get("OPENAI_BASE_URL") or None,
        openai_model=os.environ.get("OPENAI_MODEL", "").strip(),
        summarizer_backend=_env_token("SUMMARIZER_BACKEND", "claude"),
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
