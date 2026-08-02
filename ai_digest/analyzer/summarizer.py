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
#  build_report declares the expected JSON schema and the model invokes
#  it, so the answer arrives as a dictionary instead of prose that would
#  have to be parsed heuristically. Categories are not restricted to an
#  enumeration on purpose, because the relevant themes change from day
#  to day; colors are derived from the label later on.
#
#  Anthropic-compatible endpoints do not all behave the same way here.
#  Some ignore a named tool_choice, and some spend the whole output
#  budget on thinking before they ever call the tool. The thinking_mode
#  and tool_choice_mode arguments shape the request for those, and the
#  defaults keep the request Anthropic sees unchanged. An endpoint that
#  writes the report as JSON text instead of calling the tool is read
#  by text_json_fallback, which stays off until a raw response has
#  shown that it really does answer that way.
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
#  v1.1 2026-08-02
#       Let the caller disable the thinking output and choose between a
#       named, an unnamed and an automatic tool choice, accept a report
#       written as JSON text when asked to, cap the SDK retries at one
#       request per run when asked to, so that an
#       Anthropic-compatible endpoint which returns no tool_use block
#       can be configured to return one. Report the stop reason and the
#       block types when the tool call is missing, report a truncated or
#       unparsable set of arguments as such, accept only a build_report
#       block, summarize the response at info level and keep the full
#       body for debug level.
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
    "通常の回答文や思考過程を出力せず、必ず build_report ツールを"
    "呼び出してください。"
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


def _block_types(message: Any) -> List[str]:
    """ List the content block types of a response, in order. """
    return [
        getattr(block, "type", "unknown")
        for block in getattr(message, "content", [])
    ]


def _text_json_report(message: Any) -> Optional[Dict[str, Any]]:
    """
    Read a report written as JSON text instead of as a tool call.

    Returns None unless a text block parses into an object holding a
    'topics' list. That condition is the whole safety of this path: an
    endpoint explaining itself in prose, or answering with some other
    JSON, must not be mistaken for a report. A fenced block is unwrapped
    first, since models routinely wrap JSON in Markdown.
    """
    for block in getattr(message, "content", []):
        if getattr(block, "type", "") != "text":
            continue
        text = (getattr(block, "text", "") or "").strip()
        if text.startswith("```"):
            fenced = text.split("```")
            if len(fenced) < 3:
                continue
            text = fenced[1]
            if text.lower().startswith("json"):
                text = text[4:]
            text = text.strip()
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            continue
        try:
            payload = json.loads(text[start:end + 1])
        except ValueError:
            continue
        if isinstance(payload, dict) and isinstance(payload.get("topics"),
                                                    list):
            return payload
    return None


def _extract_tool_input(message: Any,
                        text_json_fallback: bool = False) -> Dict[str, Any]:
    """
    Return the build_report arguments contained in an API response.

    Only a block named build_report is accepted, so that a model which
    calls something else does not have its arguments read as a report.

    A RuntimeError is raised otherwise, and the message says which of
    the failures happened, because each needs a different answer. A
    model that used up max_tokens while thinking has to be told not to
    think; one that stopped in the middle of the arguments wrote a
    report too long for the budget; one that ended its turn with text
    ignored the tool altogether.
    """
    stop_reason = getattr(message, "stop_reason", None)
    for block in getattr(message, "content", []):
        if (getattr(block, "type", "") == "tool_use"
                and getattr(block, "name", "") == "build_report"):
            # Arguments cut off mid-write parse into a partial report,
            # or into nothing at all. Neither is worth publishing.
            if stop_reason == "max_tokens":
                raise RuntimeError(
                    "Model hit max_tokens while writing the build_report "
                    "arguments, so the report is truncated; lower "
                    "MAX_TOPICS or raise MAX_OUTPUT_TOKENS."
                )
            tool_input = getattr(block, "input", {})
            if isinstance(tool_input, str):
                try:
                    tool_input = json.loads(tool_input)
                except ValueError as error:
                    raise RuntimeError(
                        "Model returned build_report arguments that are "
                        "not valid JSON: {0}.".format(error)
                    )
            return tool_input

    if text_json_fallback:
        payload = _text_json_report(message)
        if payload is not None:
            logger.warning("no tool call; read the report from a text block "
                           "because ANTHROPIC_TEXT_JSON_FALLBACK=enabled")
            return payload

    types = _block_types(message)
    if stop_reason == "max_tokens" and "thinking" in types:
        raise RuntimeError(
            "Model exhausted max_tokens in thinking before returning the "
            "build_report tool call; set ANTHROPIC_THINKING_MODE=disabled."
        )
    raise RuntimeError(
        "Model returned no build_report tool call; stop_reason={0}, "
        "content_types={1}.".format(stop_reason, ",".join(types) or "none")
    )


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
                  base_url: Optional[str],
                  max_retries: Optional[int] = None) -> Any:
    """
    Build a client for Anthropic or an Anthropic-compatible API.

    max_retries is passed through when given. Setting it to 0 makes a
    run spend exactly one request, which is what comparing two endpoint
    settings needs: the SDK otherwise retries some errors on its own
    and two runs are no longer one request each.
    """
    import anthropic

    if api_key and auth_token:
        raise RuntimeError("Configure either an API key or a Bearer token, not both.")
    if not api_key and not auth_token:
        raise RuntimeError("Anthropic authentication is not configured.")

    options: Dict[str, Any] = {}
    if max_retries is not None:
        options["max_retries"] = max_retries
    if api_key:
        options["api_key"] = api_key
    else:
        options["auth_token"] = auth_token or ""
    if base_url:
        options["base_url"] = base_url
    return anthropic.Anthropic(**options)


def _build_request(candidates: List[Entry], model: str, max_topics: int,
                   thinking_mode: str,
                   tool_choice_mode: str) -> Dict[str, Any]:
    """
    Assemble the keyword arguments of one messages.create() call.

    The request is built as a dictionary because two of its keys are
    conditional: extra_body is only sent when the thinking output has to
    be turned off, and tool_choice has two shapes.
    """
    request: Dict[str, Any] = {
        "model": model,
        "max_tokens": MAX_OUTPUT_TOKENS,
        "system": SYSTEM_PROMPT,
        "tools": [BUILD_REPORT_TOOL],
        "messages": [{
            "role": "user",
            "content": build_prompt(candidates, max_topics),
        }],
    }

    if tool_choice_mode == "auto":
        request["tool_choice"] = {
            "type": "auto",
            "disable_parallel_tool_use": True,
        }
    elif tool_choice_mode == "any":
        # No name is sent, which is unambiguous because build_report is
        # the only tool offered. An endpoint that drops a named
        # tool_choice may still honour this one.
        request["tool_choice"] = {"type": "any"}
    else:
        request["tool_choice"] = {
            "type": "tool",
            "name": "build_report",
        }

    # Undocumented by the Messages API, so it travels in extra_body.
    if thinking_mode == "disabled":
        request["extra_body"] = {
            "thinking": {
                "type": "disabled",
            },
        }
    return request


def summarize(entries: List[Entry], api_key: Optional[str], model: str,
              max_topics: int, base_url: Optional[str] = None,
              auth_token: Optional[str] = None,
              thinking_mode: str = "default",
              tool_choice_mode: str = "forced",
              text_json_fallback: bool = False,
              max_retries: Optional[int] = None) -> List[Topic]:
    """
    Cluster and summarize collected entries with the Claude API.

    Args:
        entries: Deduplicated entries, newest and most relevant first.
        api_key: Anthropic API key.
        model: Model identifier, e.g. 'claude-sonnet-4-5'.
        max_topics: Maximum number of topics to keep.
        base_url: Optional Anthropic-compatible API base URL.
        auth_token: Optional Bearer token used instead of an API key.
        thinking_mode: 'default' sends no thinking parameter,
            'disabled' asks the endpoint to answer without thinking.
        tool_choice_mode: 'forced' names build_report, 'any' demands
            some tool without naming it, 'auto' lets the model choose
            and disables parallel tool use.
        text_json_fallback: Accept a report written as JSON text when
            no tool call came back.
        max_retries: Retries the SDK may spend on one request. None
            keeps the SDK default; 0 spends exactly one request.

    Returns:
        Topics in decreasing order of importance, without images yet.
        An empty input yields an empty list without calling the API.

    Raises:
        RuntimeError: The model answered without invoking build_report.
    """
    if not entries:
        return []

    candidates = entries[:MAX_INPUT_ENTRIES]
    client = _build_client(api_key, auth_token, base_url, max_retries)
    message = client.messages.create(**_build_request(
        candidates, model, max_topics, thinking_mode, tool_choice_mode,
    ))

    # Report the shape of the answer, not the answer itself: the body
    # runs into thousands of tokens and would swamp the cron log.
    usage = getattr(message, "usage", None)
    logger.info(
        "api response: id=%s model=%s stop_reason=%s content_types=%s "
        "input_tokens=%s output_tokens=%s",
        getattr(message, "id", None),
        getattr(message, "model", None),
        getattr(message, "stop_reason", None),
        ",".join(_block_types(message)) or "none",
        getattr(usage, "input_tokens", None),
        getattr(usage, "output_tokens", None),
    )
    if logger.isEnabledFor(logging.DEBUG):
        logger.debug("raw API response:\n%s",
                     message.model_dump_json(indent=2))

    topics = to_topics(_extract_tool_input(message, text_json_fallback),
                       candidates, max_topics)
    logger.info("summarized %d entries into %d topics",
                len(candidates), len(topics))
    return topics
