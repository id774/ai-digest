#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# app.py: Flask viewer of ai-digest
#
#  Description:
#  This module serves the reports produced by cli.py. It is read only:
#  no route collects data or calls the Claude API, so the web process
#  needs neither an API key nor outbound network access, and a slow or
#  failing batch cannot affect the site.
#
#  Routes:
#      /                          list of the stored report dates
#      /reports/<date>            report of one day, rendered from JSON
#      /reports/<date>/image      composite summary PNG of that day
#      /reports/<date>/assets/<f> topic illustration of that day
#      /healthz                   liveness probe for process managers
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - Flask 3.x
#
#  Usage:
#      flask --app app run --debug
#      gunicorn app:app --bind 0.0.0.0:${PORT}
#
#  Version History:
#  v1.1 2026-08-02
#       Register the safe_url filter used by the source links.
#  v1.0 2026-07-25
#       Initial release.
#
########################################################################

import os

from flask import Flask, abort, render_template, send_from_directory

from ai_digest import category_color, safe_url
from ai_digest.render import STATIC_DIR, TEMPLATE_DIR
from ai_digest.storage import (is_valid_date, list_dates, load_report,
                               report_dir, summary_image_path)
from config import load_config

config = load_config()

app = Flask(__name__, template_folder=TEMPLATE_DIR, static_folder=STATIC_DIR)

# Templates render both here and in the batch renderer, so the color
# helper, the link guard and the standalone switch have to be defined
# for both.
app.jinja_env.globals["category_color"] = category_color
app.jinja_env.globals["standalone"] = False
app.jinja_env.filters["safe_url"] = safe_url


@app.route("/")
def index():
    """ Show every stored report date, newest first. """
    return render_template("index.html", dates=list_dates(config.data_dir))


@app.route("/reports/<date>")
def report(date: str):
    """ Show one daily report. """
    stored = load_report(config.data_dir, date)
    if stored is None:
        abort(404)
    return render_template("report.html", date=stored["date"],
                           topics=stored["topics"], stats=stored["stats"])


@app.route("/reports/<date>/image")
def report_image(date: str):
    """ Serve the composite summary image of one day. """
    path = summary_image_path(config.data_dir, date)
    if path is None:
        abort(404)
    return send_from_directory(os.path.dirname(path),
                               os.path.basename(path))


@app.route("/reports/<date>/assets/<path:filename>")
def report_asset(date: str, filename: str):
    """
    Serve a topic illustration.

    send_from_directory rejects paths escaping the report directory, and
    the date itself is validated before it is turned into a path.
    """
    if not is_valid_date(date):
        abort(404)
    directory = report_dir(config.data_dir, date)
    if not os.path.isdir(directory):
        abort(404)
    return send_from_directory(directory, filename)


@app.route("/healthz")
def healthz():
    """ Return a plain text liveness response. """
    return "ok", 200, {"Content-Type": "text/plain; charset=utf-8"}


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=config.port)
