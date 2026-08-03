#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/collectors/__init__.py: Source collectors
#
#  Description:
#  This subpackage gathers the raw material of a daily report. Each
#  module exposes a single collect() function which returns an
#  ai_digest.CollectionResult and never raises on network errors: a
#  source that cannot be reached simply contributes nothing, so one
#  broken feed does not abort the daily batch. The result carries the
#  entries together with the per source outcome, so that an empty run
#  can be reported as unreachable sources or as an empty window rather
#  than as both at once.
#
#  Modules:
#      arxiv     - arXiv Atom API, filtered by category and age
#      news_rss  - arbitrary RSS/Atom feeds, filtered by age
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

from ai_digest.collectors import arxiv, news_rss

__all__ = ["arxiv", "news_rss"]
