#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/analyzer/plain.py: API-free mechanical summarizer
#
#  Description:
#  This module builds daily topics without calling any language model.
#  It exists so that the whole pipeline can run with
#  SUMMARIZER_BACKEND=plain and no ANTHROPIC_API_KEY at all.
#
#  Unlike summarizer.py, entries are neither clustered nor translated:
#  each deduplicated entry becomes its own topic, newest first, and the
#  bullets are sentences lifted verbatim from the original abstract or
#  feed summary. The category label is derived from the entry's origin
#  instead of being chosen freely by a model. The trade-off is accepted
#  in exchange for requiring no API key and no extra dependency.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Standard library only
#
#  Version History:
#  v1.0 2026-07-26
#       Initial release.
#
########################################################################

import re
from typing import List

from ai_digest import Entry, Topic

# Bullets kept per topic, matching the upper bound summarizer.py uses.
MAX_BULLETS = 4

# Characters kept from a bullet sentence before it is truncated.
BULLET_CHARS = 160

# Splits an abstract into sentences on the terminators common to both
# English and Japanese text.
SENTENCE_PATTERN = re.compile(r"(?<=[.!?。！？])\s+")


def _split_sentences(summary: str) -> List[str]:
    """ Split an abstract into sentence sized bullet candidates. """
    sentences = [part.strip() for part in SENTENCE_PATTERN.split(summary)
                if part.strip()]
    if sentences:
        return sentences
    return [summary.strip()] if summary.strip() else []


def _bullets(entry: Entry) -> List[str]:
    """ Return up to MAX_BULLETS bullets built from an entry's summary. """
    bullets = []
    for sentence in _split_sentences(entry.summary)[:MAX_BULLETS]:
        if len(sentence) > BULLET_CHARS:
            sentence = sentence[:BULLET_CHARS - 1].rstrip() + "…"
        bullets.append(sentence)
    if not bullets:
        bullets.append(entry.title)
    return bullets


def _category(entry: Entry) -> str:
    """ Derive a category label from the entry's origin, no model needed. """
    if entry.source_type == "paper":
        return entry.origin or "arXiv"
    return entry.origin or "News"


def summarize(entries: List[Entry], max_topics: int) -> List[Topic]:
    """
    Build topics mechanically, without any language model call.

    Args:
        entries: Deduplicated entries.
        max_topics: Maximum number of topics to keep.

    Returns:
        Topics in newest-first order, without images yet. Titles and
        bullets stay in the language of the source, since no model is
        available to translate or paraphrase them.
    """
    ordered = sorted(entries, key=lambda item: item.published, reverse=True)
    topics = []
    for entry in ordered[:max_topics]:
        topics.append(Topic(
            category=_category(entry),
            title=entry.title,
            bullets=_bullets(entry),
            sources=[{"title": entry.title, "url": entry.url}],
        ))
    return topics
