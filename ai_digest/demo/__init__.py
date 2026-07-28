#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/demo/__init__.py: Bundled demo report
#
#  Description:
#  This subpackage backs 'python cli.py demo', which builds a report
#  from data shipped with the repository instead of from the network.
#  It exists so that a fresh clone can show what a finished report looks
#  like before an API key is configured.
#
#  Two stages of the pipeline are replaced, because both need outbound
#  access. Collection is replaced by the 'entries' array of
#  sample_input.json, and summarization by its 'build_report' object,
#  which holds the arguments the Claude API would have returned for the
#  build_report tool call. Everything downstream is the pipeline itself:
#  the payload is validated by summarizer.to_topics(), and the caller
#  illustrates, stores and renders the result as usual.
#
#  The sample is data, not a recording of one API response, so a demo
#  run costs nothing, needs no key and renders identically everywhere.
#  See doc/DEMO.md for how it differs from a live report.
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
#  v1.0 2026-07-28
#       Initial release.
#
########################################################################

import json
import os
from typing import Any, Dict, List, Optional, Tuple

from ai_digest import Entry, Topic
from ai_digest.analyzer.summarizer import to_topics

# Sample shipped with the repository, used when no other file is given.
SAMPLE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "sample_input.json")

__all__ = ["SAMPLE_PATH", "load_sample", "build_topics"]


def load_sample(path: Optional[str] = None) -> Dict[str, Any]:
    """
    Read a demo sample.

    Args:
        path: Sample to read, or None for the bundled one.

    Returns:
        The parsed sample.

    Raises:
        OSError: The file cannot be read.
        ValueError: The file is not valid JSON.
    """
    with open(path or SAMPLE_PATH, encoding="utf-8") as handle:
        return json.load(handle)


def build_topics(max_topics: int, path: Optional[str] = None
                 ) -> Tuple[str, List[Topic], int]:
    """
    Build the topics of a demo report.

    The stored build_report payload goes through the same conversion as
    a real tool call, so a malformed sample is rejected exactly as a
    malformed model answer would be.

    Args:
        max_topics: Maximum number of topics to keep.
        path: Sample to read, or None for the bundled one.

    Returns:
        The report date, the topics without images yet, and the number
        of entries the sample stands in for.

    Raises:
        KeyError: The sample lacks a required key.
        OSError: The file cannot be read.
        ValueError: The file is not valid JSON.
    """
    sample = load_sample(path)
    entries: List[Entry] = [Entry.from_dict(item)
                            for item in sample["entries"]]
    topics = to_topics(sample["build_report"], entries, max_topics)
    return sample["date"], topics, len(entries)
