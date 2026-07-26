#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/images/__init__.py: Topic illustration handling
#
#  Description:
#  This subpackage provides the illustration attached to every topic of
#  a report. Two strategies are combined:
#
#      resolver  - try to download a real image from the source page
#      fallback  - draw a card locally with Pillow when that fails
#
#  Scraping is best effort by design. Sites change their markup, block
#  robots or serve images the application cannot decode, and none of
#  that is allowed to break the daily batch, so every failure falls back
#  to a generated card.
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

from ai_digest.images import fallback, resolver

__all__ = ["fallback", "resolver"]
