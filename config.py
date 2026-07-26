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
#  - ANTHROPIC_MODEL
#      Model name used for summarization. Defaults to a Claude Sonnet
#      model; override it when a different model is preferred.
#  - SUMMARIZER_BACKEND
#      'claude' (default) calls the Claude API for clustering,
#      translation and classification. 'plain' skips the API entirely
#      and builds topics mechanically, so the batch can run without
#      ANTHROPIC_API_KEY at the cost of translation and clustering
#      quality.
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
#  - AI_DIGEST_FONT_PATH
#      Path of a CJK capable TrueType font used for image generation.
#  - DATA_DIR
#      Directory where generated reports are stored.
#  - HTTP_TIMEOUT
#      Timeout, in seconds, applied to every outgoing HTTP request.
#  - USER_AGENT
#      User-Agent header sent with every outgoing HTTP request.
#  - PORT
#      TCP port used by the development server.
#
#  Version History:
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
# 'plain' builds topics mechanically and needs no API key.
SUMMARIZER_BACKENDS = ("claude", "plain")

# Default arXiv categories: artificial intelligence, machine learning
# and computation and language.
DEFAULT_ARXIV_CATEGORIES = "cs.AI,cs.LG,cs.CL"

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


def _split_csv(value: str) -> List[str]:
    """ Split a comma separated environment value into a clean list. """
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


def _env_choice(name: str, default: str, choices: tuple) -> str:
    """ Read a string environment variable constrained to choices. """
    raw = os.environ.get(name, "").strip().lower()
    if raw in choices:
        return raw
    return default


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
    anthropic_model: str = "claude-sonnet-4-5"
    summarizer_backend: str = "claude"
    arxiv_categories: List[str] = field(default_factory=list)
    arxiv_max_results: int = 60
    news_feed_urls: List[str] = field(default_factory=list)
    lookback_hours: int = 24
    max_topics: int = 6
    font_path: Optional[str] = None
    data_dir: str = os.path.join(BASE_DIR, "data", "reports")
    http_timeout: int = 15
    user_agent: str = "ai-digest/1.0 (+https://github.com/id774/ai-digest)"
    port: int = 5000

    def require_api_key(self) -> str:
        """
        Return the Claude API key or raise when it is missing.

        The batch pipeline calls this before any network access so that
        a misconfigured environment fails immediately instead of after
        the collection stage.
        """
        if not self.anthropic_api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Export it or place it in .env."
            )
        return self.anthropic_api_key


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
        anthropic_model=os.environ.get("ANTHROPIC_MODEL", "claude-sonnet-4-5").strip()
        or "claude-sonnet-4-5",
        summarizer_backend=_env_choice(
            "SUMMARIZER_BACKEND", "claude", SUMMARIZER_BACKENDS
        ),
        arxiv_categories=_split_csv(
            os.environ.get("ARXIV_CATEGORIES", DEFAULT_ARXIV_CATEGORIES)
        ),
        arxiv_max_results=_env_int("ARXIV_MAX_RESULTS", 60),
        news_feed_urls=_split_csv(
            os.environ.get("NEWS_FEED_URLS", DEFAULT_NEWS_FEED_URLS)
        ),
        lookback_hours=_env_int("LOOKBACK_HOURS", 24),
        max_topics=_env_int("MAX_TOPICS", 6),
        font_path=detect_font_path(os.environ.get("AI_DIGEST_FONT_PATH")),
        data_dir=os.path.abspath(data_dir),
        http_timeout=_env_int("HTTP_TIMEOUT", 15),
        user_agent=os.environ.get(
            "USER_AGENT",
            "ai-digest/1.0 (+https://github.com/id774/ai-digest)",
        ),
        port=_env_int("PORT", 5000),
    )
