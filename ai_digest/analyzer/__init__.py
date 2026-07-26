#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/analyzer/__init__.py: Language model analysis
#
#  Description:
#  This subpackage turns the deduplicated collection of papers and news
#  articles into the curated topics of a daily report. summarizer calls
#  the Claude API through the Anthropic tool use interface so that the
#  answer is a validated JSON structure instead of free form prose.
#  plain builds the same Topic structure mechanically, without any
#  language model, for SUMMARIZER_BACKEND=plain.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#
#  Version History:
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

from ai_digest.analyzer import plain, summarizer

__all__ = ["plain", "summarizer"]
