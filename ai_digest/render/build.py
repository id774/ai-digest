#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# ai_digest/render/build.py: Static HTML rendering
#
#  Description:
#  This module renders a stored report into a standalone HTML file using
#  the same Jinja2 templates as the Flask viewer. The file is written
#  next to the report data as index.html, so that a day can be published
#  by copying its directory to any static web server, or opened directly
#  from the file system when no server is running.
#
#  The Flask application does not depend on this module; it renders the
#  same templates on demand. Batch rendering exists only to make the
#  archive self contained.
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Jinja2 (installed together with Flask)
#
#  Version History:
#  v1.1 2026-08-02
#       Register the safe_url filter used by the source links.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import logging
import os
import shutil
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from ai_digest import Topic, category_color, safe_url
from ai_digest.render import STATIC_DIR, TEMPLATE_DIR

logger = logging.getLogger(__name__)


def create_environment() -> Environment:
    """
    Return the Jinja2 environment shared by every renderer.

    Autoescaping is enabled because topic titles and bullets come from
    a language model reading arbitrary web pages. Escaping alone does
    not make a source link safe to click, so the safe_url filter is
    registered here and applied to every href the templates emit.
    """
    environment = Environment(
        loader=FileSystemLoader(TEMPLATE_DIR),
        autoescape=select_autoescape(["html"]),
    )
    environment.globals["category_color"] = category_color
    environment.filters["safe_url"] = safe_url
    return environment


def render_report(date: str, topics: List[Topic], stats: Dict[str, Any],
                  standalone: bool = True) -> str:
    """
    Render the HTML of one report.

    Args:
        date: Report date in YYYY-MM-DD form.
        topics: Topics of the report, in display order.
        stats: Counters describing the run, shown in the footer.
        standalone: When True, asset URLs point at files sitting next to
            the HTML instead of the Flask routes.

    Returns:
        The rendered HTML document.
    """
    template = create_environment().get_template("report.html")
    return template.render(date=date, topics=topics, stats=stats,
                           standalone=standalone)


def write_report_html(report_dir: str, date: str, topics: List[Topic],
                      stats: Dict[str, Any]) -> str:
    """
    Write index.html and its stylesheet into a report directory.

    Returns:
        The path of the written HTML file.
    """
    html = render_report(date, topics, stats, standalone=True)
    output_path = os.path.join(report_dir, "index.html")
    with open(output_path, "w", encoding="utf-8") as handle:
        handle.write(html)

    stylesheet = os.path.join(STATIC_DIR, "style.css")
    if os.path.isfile(stylesheet):
        shutil.copyfile(stylesheet, os.path.join(report_dir, "style.css"))

    logger.info("rendered report HTML at %s", output_path)
    return output_path
