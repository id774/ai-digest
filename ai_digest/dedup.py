#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/dedup.py: Near duplicate removal
#
#  Description:
#  Papers announced on arXiv are frequently reported by several news
#  outlets on the same day, and some outlets syndicate each other. This
#  module removes such near duplicates before the collected material is
#  sent to the language model, which keeps the prompt small and avoids
#  paying for redundant input tokens.
#
#  Similarity is measured on normalized titles with
#  difflib.SequenceMatcher, plus an exact URL check. The approach is
#  intentionally simple: the language model clusters the remaining
#  entries anyway, so only obvious repetitions need to be dropped here.
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
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import logging
import re
import unicodedata
from difflib import SequenceMatcher
from typing import List

from ai_digest import Entry

# Titles above this similarity ratio are considered the same story.
DEFAULT_THRESHOLD = 0.85

# Everything that is neither a letter nor a digit is dropped before the
# comparison, so that punctuation and quoting styles do not matter.
NON_WORD_PATTERN = re.compile(r"[^0-9a-z\u3040-\u30ff\u4e00-\u9fff]+")

logger = logging.getLogger(__name__)


def normalize_title(title: str) -> str:
    """
    Return a comparison key for a title.

    The title is case folded, converted to its NFKC form so that full
    width characters match their half width counterparts, and stripped
    of punctuation and whitespace.
    """
    folded = unicodedata.normalize("NFKC", title).lower()
    return NON_WORD_PATTERN.sub("", folded)


def is_similar(left: str, right: str, threshold: float) -> bool:
    """ Return True when two normalized titles describe one story. """
    if not left or not right:
        return False
    if left == right:
        return True
    return SequenceMatcher(None, left, right).ratio() >= threshold


def deduplicate(entries: List[Entry],
                threshold: float = DEFAULT_THRESHOLD) -> List[Entry]:
    """
    Drop near duplicate entries, keeping the first occurrence.

    The input order decides which entry survives, so callers should
    sort by preference beforehand; the pipeline passes papers first so
    that the primary source outranks the reporting about it.

    Args:
        entries: Collected entries, in order of preference.
        threshold: Title similarity ratio above which entries merge.

    Returns:
        The filtered list, in the original order.
    """
    kept: List[Entry] = []
    kept_keys: List[str] = []
    seen_urls = set()

    for entry in entries:
        if entry.url in seen_urls:
            continue
        key = normalize_title(entry.title)
        if any(is_similar(key, other, threshold) for other in kept_keys):
            continue
        seen_urls.add(entry.url)
        kept_keys.append(key)
        kept.append(entry)

    logger.info("deduplicated %d entries into %d", len(entries), len(kept))
    return kept
