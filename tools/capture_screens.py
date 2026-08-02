#!/usr/bin/env python
# -*- coding: utf-8 -*-

########################################################################
# tools/capture_screens.py: Screenshots of the Flask viewer
#
#  Description:
#  This script captures the screenshots embedded in the README. It
#  starts the read only Flask viewer on a loopback port, drives a
#  headless Chromium over the archive already on disk and writes one PNG
#  per page into doc/screenshots/.
#
#  It reads whatever DATA_DIR contains, so the screenshots reflect a
#  real batch run when one has been performed, and the bundled demo
#  otherwise:
#
#      python cli.py demo                 # or 'run', which needs a key
#      python tools/capture_screens.py
#
#  The viewer never calls the Claude API, so this script needs no API
#  key of its own whatever produced the archive it renders.
#
#  It is a documentation tool and is not part of the application;
#  nothing under ai_digest/ imports it, and Playwright is deliberately
#  absent from requirements.txt because the application does not need a
#  browser at run time. Install it separately:
#
#      pip install playwright && playwright install chromium
#
#  Author: id774 (More info: http://id774.net)
#  Source Code: https://github.com/id774/ai-digest
#  License: The GPL version 3, or LGPL version 3 (Dual License).
#  Contact: idnanashi@gmail.com
#
#  Usage:
#      python tools/capture_screens.py [--data-dir DIR] [--date DATE]
#                                      [--output DIR] [--port PORT]
#                                      [--scale N] [--browser PATH]
#
#  Options:
#  - --data-dir DIR
#      Archive to render. Defaults to DATA_DIR.
#  - --date DATE
#      Report to capture. Defaults to the newest stored report.
#  - --output DIR
#      Destination of the PNG files. Defaults to doc/screenshots.
#  - --port PORT
#      Loopback port the viewer is started on. Defaults to 5099.
#  - --scale N
#      Device pixel ratio of the capture. Defaults to 1, which keeps the
#      files small enough to live in the repository; 2 gives a HiDPI
#      capture at roughly four times the size.
#  - --browser PATH
#      Chromium executable, when the one bundled with Playwright is not
#      the one to use.
#
#  Exit Codes:
#  - 0: The screenshots were written.
#  - 1: The archive holds no report, or the viewer did not come up.
#
#  Requirements:
#  - Python Version: 3.9 or later
#  - See requirements.txt
#  - playwright, and a Chromium downloaded by it
#
#  Version History:
#  v1.0 2026-07-28
#       Initial release.
#
########################################################################

import argparse
import logging
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request

# The repository root, so that the script runs from anywhere.
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from ai_digest.storage import list_dates  # noqa: E402
from config import load_config            # noqa: E402

DEFAULT_OUTPUT = os.path.join(BASE_DIR, "doc", "screenshots")
DEFAULT_PORT = 5099

# Viewport widths captured for every page. The narrow one documents
# that the stylesheet collapses the topic grid to a single column.
VIEWPORTS = (
    ("desktop", 1280),
    ("mobile", 414),
)

# Viewport height. Screenshots are taken full page, so this is only the
# lower bound: a long report grows past it, while the short archive
# index is captured without a screen of empty background below it.
VIEWPORT_HEIGHT = 480

# Seconds waited for the viewer to answer on /healthz before giving up.
STARTUP_TIMEOUT = 30

logger = logging.getLogger("ai_digest.tools.capture")


def parse_args(argv=None):
    """ Build the command line parser and parse the arguments. """
    parser = argparse.ArgumentParser(
        prog="capture_screens.py",
        description="Capture screenshots of the ai-digest viewer.",
    )
    parser.add_argument("--data-dir", help="archive to render")
    parser.add_argument("--date", help="report date, YYYY-MM-DD")
    parser.add_argument("--output", default=DEFAULT_OUTPUT,
                        help="destination directory")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT,
                        help="loopback port of the viewer")
    parser.add_argument("--scale", type=int, default=1,
                        help="device pixel ratio, 2 for a HiDPI capture")
    parser.add_argument("--browser", help="Chromium executable to use")
    return parser.parse_args(argv)


def wait_until_up(base_url, process):
    """
    Block until the viewer answers on /healthz.

    Returns:
        True when the viewer is serving, False when it exited or did not
        come up within STARTUP_TIMEOUT.
    """
    deadline = time.time() + STARTUP_TIMEOUT
    while time.time() < deadline:
        if process.poll() is not None:
            return False
        try:
            with urllib.request.urlopen(base_url + "/healthz", timeout=2):
                return True
        except (urllib.error.URLError, OSError):
            time.sleep(0.3)
    return False


def capture(page_url, output_path, browser, width, scale):
    """ Write one full page screenshot of a URL. """
    context = browser.new_context(viewport={"width": width,
                                            "height": VIEWPORT_HEIGHT},
                                  device_scale_factor=scale)
    page = context.new_page()
    page.goto(page_url, wait_until="networkidle")
    page.screenshot(path=output_path, full_page=True)
    context.close()
    logger.info("wrote %s", output_path)


def main(argv=None):
    """ Entry point returning the process exit code. """
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        stream=sys.stderr,
    )
    args = parse_args(argv)
    config = load_config()
    data_dir = os.path.abspath(args.data_dir or config.data_dir)

    dates = list_dates(data_dir)
    if not dates:
        logger.error("no report in %s; run 'python cli.py demo' first",
                     data_dir)
        return 1
    date = args.date or dates[0]
    if date not in dates:
        logger.error("no stored report for %s in %s", date, data_dir)
        return 1

    os.makedirs(args.output, exist_ok=True)

    # The viewer is started as a child process rather than in a thread,
    # so that it holds its own configuration and is killed cleanly even
    # when a capture raises.
    environment = dict(os.environ, DATA_DIR=data_dir, PORT=str(args.port))
    process = subprocess.Popen(
        [sys.executable, "-c",
         "import app; app.app.run(host='127.0.0.1', port={0})".format(
             args.port)],
        cwd=BASE_DIR, env=environment,
        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    base_url = "http://127.0.0.1:{0}".format(args.port)
    try:
        if not wait_until_up(base_url, process):
            logger.error("the viewer did not come up on %s", base_url)
            return 1

        from playwright.sync_api import sync_playwright

        pages = (
            ("index", base_url + "/"),
            ("report", "{0}/reports/{1}".format(base_url, date)),
        )
        with sync_playwright() as playwright:
            options = {"args": ["--no-sandbox"]}
            if args.browser:
                options["executable_path"] = args.browser
            browser = playwright.chromium.launch(**options)
            try:
                for name, url in pages:
                    for label, width in VIEWPORTS:
                        filename = "{0}-{1}.png".format(name, label)
                        capture(url, os.path.join(args.output, filename),
                                browser, width, args.scale)
            finally:
                browser.close()
    finally:
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()

    logger.info("screenshots of %s written to %s", date, args.output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
