#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/analyzer/summarizer.py: Claude based clustering and summary
#
#  Description:
#  This module asks the Claude API to read the collected entries, group
#  the ones that cover the same story, rank them by importance, label
#  each group with a freely chosen Japanese category and write a short
#  Japanese summary for it.
#
#  The call uses the Anthropic tool use interface: a tool named
#  build_report declares the expected JSON schema and the model is
#  forced to invoke it, so the answer arrives as a dictionary instead of
#  prose that would have to be parsed heuristically. Categories are not
#  restricted to an enumeration on purpose, because the relevant themes
#  change from day to day; colors are derived from the label later on.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - anthropic
#
#  Version History:
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import json
import logging
from typing import Any, Dict, List, Optional

from ai_digest import Entry, Topic

# Entries handed to the model. Sending the whole collection would be
# wasteful, and the newest items are the relevant ones anyway.
MAX_INPUT_ENTRIES = 60

# Characters of an abstract kept per entry in the prompt.
SUMMARY_CHARS = 700

# Upper bound on the response size. Six topics with four bullets each
# fit comfortably below this limit.
MAX_OUTPUT_TOKENS = 4000

SYSTEM_PROMPT = (
    "あなたは AI 技術と機械学習研究の動向を追う専門アナリストです。"
    "与えられた論文とニュースの一覧を読み、同じ話題を扱う項目をまとめ、"
    "重要度の高い順に日次ダイジェストのトピックを構成してください。"
    "出力はすべて日本語とし、英語の原文は日本語に翻訳して要約します。"
    "カテゴリ名は固定の一覧から選ぶのではなく、その日の内容に応じて"
    "適切な短い日本語のラベルを自由に付けてください。"
    "推測や誇張を避け、原文に書かれている事実のみを記述してください。"
)

# Tool schema forcing a structured answer. 'category' is a free string
# so that the model can label each topic as it sees fit.
BUILD_REPORT_TOOL = {
    "name": "build_report",
    "description": (
        "日次ダイジェストのトピック一覧を、重要度の高い順に登録する。"
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "topics": {
                "type": "array",
                "description": "重要度の高い順に並べたトピックの一覧。",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "description": (
                                "トピックを表す短い日本語のカテゴリ名。"
                                "例: 基盤モデル、推論効率、評価・ベンチマーク。"
                            ),
                        },
                        "title": {
                            "type": "string",
                            "description": "日本語の見出し。40 文字以内。",
                        },
                        "bullets": {
                            "type": "array",
                            "description": (
                                "日本語の箇条書き。2 件から 4 件。"
                                "各項目は 60 文字以内の一文。"
                            ),
                            "items": {"type": "string"},
                        },
                        "source_indexes": {
                            "type": "array",
                            "description": (
                                "このトピックの根拠となる入力項目の番号。"
                                "重要な順に最大 3 件。"
                            ),
                            "items": {"type": "integer"},
                        },
                    },
                    "required": [
                        "category", "title", "bullets", "source_indexes",
                    ],
                },
            }
        },
        "required": ["topics"],
    },
}

logger = logging.getLogger(__name__)


def build_prompt(entries: List[Entry], max_topics: int) -> str:
    """
    Render the user prompt listing every candidate entry.

    Entries are numbered so that the model can reference them in
    source_indexes instead of repeating titles and URLs, which keeps
    the response short and the citations exact.
    """
    lines = [
        "以下は過去 24 時間に公開された AI 関連の論文とニュースの一覧です。",
        "内容が重複する項目はひとつのトピックにまとめ、"
        "重要度の高い順に最大 {0} 件のトピックを作成してください。".format(
            max_topics
        ),
        "各トピックには、根拠とした項目の番号を重要な順に付けてください。",
        "",
    ]
    for index, entry in enumerate(entries):
        kind = "論文" if entry.source_type == "paper" else "ニュース"
        lines.append("[{0}] ({1}) {2}".format(index, kind, entry.title))
        if entry.origin:
            lines.append("    出典: {0}".format(entry.origin))
        if entry.summary:
            lines.append("    概要: {0}".format(entry.summary[:SUMMARY_CHARS]))
        lines.append("")
    return "\n".join(lines)


def _extract_tool_input(message: Any) -> Dict[str, Any]:
    """
    Return the build_report arguments contained in an API response.

    A RuntimeError is raised when the model answered with text only,
    which the caller reports as a failed run rather than publishing an
    empty report.
    """
    for block in getattr(message, "content", []):
        if getattr(block, "type", "") == "tool_use":
            tool_input = getattr(block, "input", {})
            if isinstance(tool_input, str):
                tool_input = json.loads(tool_input)
            return tool_input
    raise RuntimeError("Claude did not return a build_report tool call.")


def to_topics(payload: Dict[str, Any], entries: List[Entry],
              max_topics: int) -> List[Topic]:
    """
    Convert the raw tool arguments into Topic objects.

    This is public because ai_digest.demo feeds a stored payload through
    it, so that the demo report is validated exactly like a live one.

    Source indexes outside the input range are ignored, and topics
    without any usable source or bullet are dropped, so that a partial
    hallucination cannot produce a citation free block.
    """
    topics: List[Topic] = []
    for raw_topic in payload.get("topics", [])[:max_topics]:
        bullets = [
            " ".join(str(bullet).split())
            for bullet in raw_topic.get("bullets", [])
            if str(bullet).strip()
        ][:4]
        sources = []
        for index in raw_topic.get("source_indexes", [])[:3]:
            if isinstance(index, int) and 0 <= index < len(entries):
                entry = entries[index]
                sources.append({"title": entry.title, "url": entry.url})
        if not bullets or not sources:
            logger.warning("dropping malformed topic: %s",
                           raw_topic.get("title", ""))
            continue
        topics.append(Topic(
            category=str(raw_topic.get("category", "その他")).strip() or "その他",
            title=" ".join(str(raw_topic.get("title", "")).split()),
            bullets=bullets,
            sources=sources,
        ))
    return topics


def _build_client(api_key: Optional[str], auth_token: Optional[str],
                  base_url: Optional[str]) -> Any:
    """ Build a client for Anthropic or an Anthropic-compatible API. """
    import anthropic

    if api_key and auth_token:
        raise RuntimeError("Configure either an API key or a Bearer token, not both.")
    if not api_key and not auth_token:
        raise RuntimeError("Anthropic authentication is not configured.")

    options: Dict[str, str] = {}
    if api_key:
        options["api_key"] = api_key
    else:
        options["auth_token"] = auth_token or ""
    if base_url:
        options["base_url"] = base_url
    return anthropic.Anthropic(**options)


def summarize(entries: List[Entry], api_key: Optional[str], model: str,
              max_topics: int, base_url: Optional[str] = None,
              auth_token: Optional[str] = None) -> List[Topic]:
    """
    Cluster and summarize collected entries with the Claude API.

    Args:
        entries: Deduplicated entries, newest and most relevant first.
        api_key: Anthropic API key.
        model: Model identifier, e.g. 'claude-sonnet-4-5'.
        max_topics: Maximum number of topics to keep.
        base_url: Optional Anthropic-compatible API base URL.
        auth_token: Optional Bearer token used instead of an API key.

    Returns:
        Topics in decreasing order of importance, without images yet.
        An empty input yields an empty list without calling the API.

    Raises:
        RuntimeError: The model answered without invoking build_report.
    """
    if not entries:
        return []

    candidates = entries[:MAX_INPUT_ENTRIES]
    client = _build_client(api_key, auth_token, base_url)
    message = client.messages.create(
        model=model,
        max_tokens=MAX_OUTPUT_TOKENS,
        system=SYSTEM_PROMPT,
        tools=[BUILD_REPORT_TOOL],
        tool_choice={"type": "tool", "name": "build_report"},
        messages=[{
            "role": "user",
            "content": build_prompt(candidates, max_topics),
        }],
    )

    topics = to_topics(_extract_tool_input(message), candidates, max_topics)
    logger.info("summarized %d entries into %d topics",
                len(candidates), len(topics))
    return topics
