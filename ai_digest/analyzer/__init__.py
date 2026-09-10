#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/analyzer/__init__.py: Topic-editing backends
#
#  Description:
#  This subpackage turns the deduplicated collection of papers and news
#  articles into the topics of a daily report. summarizer implements the
#  anthropic-compatible Messages API route, openai_compat implements the
#  OpenAI-compatible Chat Completions route, and plain builds the same
#  Topic structure mechanically without a language model.
#
#  Author: id774 (More info: https://id774.net)
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
