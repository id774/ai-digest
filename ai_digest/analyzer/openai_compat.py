#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/analyzer/openai_compat.py: OpenAI compatible summarizer
#
#  Description:
#  This module builds the daily topics through an OpenAI compatible
#  Chat Completions API, for a provider whose Anthropic compatible
#  endpoint accepts the request but never answers with a tool_use
#  block.
#
#  It is not a fallback bolted onto summarizer.py but a second explicit
#  path: the prompt, the tool schema and the validation are shared with
#  the Anthropic one, and only the wire format differs. The Anthropic
#  tool definition is translated into an OpenAI function tool, the
#  answer is read from tool_calls[].function.arguments, and the parsed
#  arguments go through summarizer.to_topics() exactly like a Claude
#  answer, so a report built here is validated identically.
#
#  The openai package is imported inside the call and is deliberately
#  absent from requirements.txt: only this backend needs it, and the
#  default installation should not carry a second API client.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - openai, installed separately: pip install openai
#
#  Version History:
#  v1.2 2026-08-05
#       Bound one request with an explicit timeout instead of leaving
#       it to the SDK default, as the Anthropic path does.
#  v1.1 2026-08-03
#       Name the configured look back window in the prompt, like the
#       Anthropic path.
#  v1.0 2026-08-02
#       Initial release, with the output budget taken from the caller.
#
########################################################################

import json
import logging
from typing import Any, Dict, List, Optional

from ai_digest import Entry, Topic
from ai_digest.analyzer.summarizer import (BUILD_REPORT_TOOL,
                                           DEFAULT_LOOKBACK_HOURS,
                                           DEFAULT_TIMEOUT,
                                           MAX_INPUT_ENTRIES,
                                           MAX_OUTPUT_TOKENS, SYSTEM_PROMPT,
                                           build_prompt, to_topics)

logger = logging.getLogger(__name__)


def build_function_tool() -> Dict[str, Any]:
    """
    Translate the Anthropic tool definition into an OpenAI function.

    The schema itself is reused as is, so both backends ask for exactly
    the same object and a report cannot differ by the route it took.
    """
    return {
        "type": "function",
        "function": {
            "name": BUILD_REPORT_TOOL["name"],
            "description": BUILD_REPORT_TOOL["description"],
            "parameters": BUILD_REPORT_TOOL["input_schema"],
        },
    }


def _build_client(api_key: str, base_url: Optional[str],
                  max_retries: Optional[int],
                  timeout: Optional[int] = None) -> Any:
    """
    Build the OpenAI client, importing the package on demand.

    timeout bounds one request. The SDK default is measured in minutes,
    which is no bound at all for an unattended run, and each retry
    spends the timeout again.
    """
    try:
        from openai import OpenAI
    except ImportError:
        raise RuntimeError(
            "SUMMARIZER_BACKEND=openai needs the openai package, which is "
            "not part of requirements.txt. Install it with "
            "'pip install openai'."
        )

    options: Dict[str, Any] = {"api_key": api_key}
    if base_url:
        options["base_url"] = base_url
    if max_retries is not None:
        options["max_retries"] = max_retries
    if timeout is not None:
        options["timeout"] = timeout
    return OpenAI(**options)


def _extract_arguments(response: Any) -> Dict[str, Any]:
    """
    Return the build_report arguments of a Chat Completions answer.

    Only a call named build_report is read, and the arguments must parse
    into an object, so that a model answering with something else does
    not have its output published as a report. Each failure names
    itself, because a missing call and a truncated one need different
    answers.
    """
    choices = getattr(response, "choices", None) or []
    if not choices:
        raise RuntimeError("Model returned no choice at all.")

    choice = choices[0]
    finish_reason = getattr(choice, "finish_reason", None)
    message = getattr(choice, "message", None)
    for call in (getattr(message, "tool_calls", None) or []):
        function = getattr(call, "function", None)
        if getattr(function, "name", "") != BUILD_REPORT_TOOL["name"]:
            continue
        if finish_reason == "length":
            raise RuntimeError(
                "Model hit the token limit while writing the build_report "
                "arguments, so the report is truncated; lower MAX_TOPICS "
                "or raise MAX_OUTPUT_TOKENS."
            )
        raw = getattr(function, "arguments", "") or ""
        try:
            arguments = json.loads(raw) if isinstance(raw, str) else raw
        except ValueError as error:
            raise RuntimeError(
                "Model returned build_report arguments that are not valid "
                "JSON: {0}.".format(error)
            )
        if not isinstance(arguments, dict):
            raise RuntimeError(
                "Model returned build_report arguments that are not an "
                "object."
            )
        return arguments

    raise RuntimeError(
        "Model returned no build_report tool call; finish_reason={0}.".format(
            finish_reason
        )
    )


def summarize(entries: List[Entry], api_key: str, model: str,
              max_topics: int, base_url: Optional[str] = None,
              max_retries: Optional[int] = None,
              max_output_tokens: int = MAX_OUTPUT_TOKENS,
              timeout: int = DEFAULT_TIMEOUT,
              lookback_hours: int = DEFAULT_LOOKBACK_HOURS) -> List[Topic]:
    """
    Cluster and summarize collected entries over Chat Completions.

    Args:
        entries: Deduplicated entries, newest and most relevant first.
        api_key: Key of the OpenAI compatible endpoint.
        model: Model identifier as that endpoint names it.
        max_topics: Maximum number of topics to keep.
        base_url: Base URL of the endpoint, including the version path.
        max_retries: Retries the SDK may spend on one request. None
            keeps the SDK default; 0 spends exactly one request.
        max_output_tokens: Tokens the model may produce in one answer.
        timeout: Seconds allowed for one request. Each retry spends it
            again, so the worst case wait is timeout x (max_retries+1).
        lookback_hours: Age limit the collectors applied, named in the
            prompt so that it matches the material actually sent.

    Returns:
        Topics in decreasing order of importance, without images yet.
        An empty input yields an empty list without calling the API.

    Raises:
        RuntimeError: The openai package is missing, or the model
            answered without a usable build_report call.
    """
    if not entries:
        return []

    candidates = entries[:MAX_INPUT_ENTRIES]
    client = _build_client(api_key, base_url, max_retries, timeout)
    response = client.chat.completions.create(
        model=model,
        max_tokens=max_output_tokens,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",
             "content": build_prompt(candidates, max_topics,
                                     lookback_hours)},
        ],
        tools=[build_function_tool()],
        tool_choice={
            "type": "function",
            "function": {"name": BUILD_REPORT_TOOL["name"]},
        },
    )

    # Same shape as the Anthropic path logs, so that two runs against
    # the two backends can be compared line by line.
    usage = getattr(response, "usage", None)
    choice = (getattr(response, "choices", None) or [None])[0]
    logger.info(
        "api response: id=%s model=%s finish_reason=%s "
        "input_tokens=%s output_tokens=%s",
        getattr(response, "id", None),
        getattr(response, "model", None),
        getattr(choice, "finish_reason", None),
        getattr(usage, "prompt_tokens", None),
        getattr(usage, "completion_tokens", None),
    )
    if logger.isEnabledFor(logging.DEBUG):
        dump = getattr(response, "model_dump_json", None)
        logger.debug("raw API response:\n%s",
                     dump(indent=2) if dump else response)

    topics = to_topics(_extract_arguments(response), candidates, max_topics)
    logger.info("summarized %d entries into %d topics",
                len(candidates), len(topics))
    return topics
