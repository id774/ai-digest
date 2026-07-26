#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/render/__init__.py: Report rendering
#
#  Description:
#  This subpackage turns a finished report into the two artifacts the
#  application publishes:
#
#      build           - static HTML rendered with Jinja2
#      compose_image   - one composite PNG drawn with Pillow
#
#  The templates and the stylesheet used by the Flask viewer live here
#  as well, so that batch rendering and the web application share the
#  same presentation.
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

import os

TEMPLATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "templates")
STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "static")

__all__ = ["TEMPLATE_DIR", "STATIC_DIR"]
